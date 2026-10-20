"""AI 助手与 AI 解析接口。

- /chat：走 ReAct 循环，模型可调用工具（错题检索、批改）
- /explain：单轮，直接生成解析（不需要工具）
"""

import json
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import ollama

from app.agent.react import run_react_stream
from app.agent.tools import TOOLS_SCHEMA, ToolContext
from app.cache import EXPLAIN_TTL, cache, content_hash
from app.db import get_db
from app.models import Question, QuestionBank
from app.rag.context import (
    build_query,
    format_context,
    kp_names_for_question,
    render_context_block,
)
from app.rag.service import retrieve
from app.routes.banks import current_user_id

router = APIRouter(prefix="/api/ai", tags=["ai"])

AI_API_BASE = os.getenv("AI_API_BASE", "http://localhost:11434")
AI_MODEL = os.getenv("AI_MODEL", "qwen2.5:7b")

# 没抢到重建锁时，最多等多久别人回填缓存（秒）。
# 要大于「单次模型生成时间」，否则等待方会在别人还没生成完时超时并重复回源。
# 本机 gemma3:4b 实测单次约 56s，所以默认给到 120s。
CACHE_WAIT_TIMEOUT = float(os.getenv("CACHE_WAIT_TIMEOUT", "120"))
# 重建锁的持有时间上限，防止持锁进程崩了以后锁不释放
LOCK_TTL = int(os.getenv("CACHE_LOCK_TTL", "180"))
# 缓存文本回放时的分片大小，保持和真实流式一样的 SSE 分片粒度
REPLAY_CHUNK = 48


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatBody(BaseModel):
    question_id: int
    messages: list[ChatMessage]


class ExplainBody(BaseModel):
    question_id: int
    user_answer: str = ""
    # ---- RAG 开关（默认开启，关掉就退回原来的纯模型讲解）----
    use_rag: bool = True
    rag_top_k: int = Field(default=5, ge=1, le=10)
    rag_alpha: float = Field(default=0.5, ge=0.0, le=1.0)


def build_question_context(question: Question, include_answer: bool = False) -> str:
    """拼出题目的文本上下文。"""
    lines = [f"题目：{question.stem}"]

    if question.question_type in ("single", "multiple", "judge"):
        letters = "ABCDEFGH"
        for i, opt in enumerate(question.options or []):
            lines.append(f"{letters[i]}. {opt}")
        lines.append(f"题型：{question.question_type}")
    elif question.question_type == "blank":
        lines.append("题型：填空题")
    elif question.question_type == "short":
        lines.append("题型：简答题")
    elif question.question_type == "calc":
        lines.append("题型：计算题")

    if include_answer:
        lines.append(f"正确答案：{question.correct_answer}")
        if question.explanation:
            lines.append(f"官方解析：{question.explanation}")

    return "\n".join(lines)


def get_owned_question(question_id: int, user_id: int, db: Session) -> Question:
    """确认题目属于当前用户，否则抛 404。"""
    q = (
        db.query(Question)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(
            Question.id == question_id,
            QuestionBank.user_id == user_id,
            Question.is_archived.is_(False),
        )
        .first()
    )
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    return q


# ============================================================
# AI 助手对话（带工具调用）
# ============================================================

@router.post("/chat")
async def ai_chat(
    body: ChatBody,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    question = get_owned_question(body.question_id, user_id, db)

    system_prompt = (
        "你是一个专业的错题本 AI 学习助手。"
        "你会收到一道正在练习的题目，帮助用户理解这道题。\n\n"
        "你可以使用以下工具：\n"
        "- search_wrong_questions：搜索用户的错题\n"
        "- grade_calculation：批改计算题/简答题/填空题\n\n"
        "使用原则：\n"
        "1. 用户可以问知识点、解题思路，你正常回答。\n"
        "2. 用户问'我错过哪些类似的题'时，调用 search_wrong_questions。\n"
        "3. 用户给出自己的解答问'对不对'时，调用 grade_calculation。\n"
        "4. 不要直接给最终答案，除非用户已经提交过答案，或明确要求查看答案。\n"
        "5. 回答简洁、清晰，适合学生理解。\n\n"
        f"【当前题目】\n{build_question_context(question, include_answer=False)}"
    )

    client = ollama.Client(host=AI_API_BASE)
    ctx = ToolContext(db=db, user_id=user_id)

    user_messages = [{"role": m.role, "content": m.content} for m in body.messages]

    return StreamingResponse(
        run_react_stream(
            client=client,
            model=AI_MODEL,
            system_prompt=system_prompt,
            user_messages=user_messages,
            tools_schema=TOOLS_SCHEMA,
            tool_context=ctx,
        ),
        media_type="text/event-stream",
    )


# ============================================================
# AI 解析（单轮，无工具；带 Redis 缓存）
# ============================================================

def explain_cache_key(question: Question, user_answer: str,
                      rag_sig: str = "norag") -> tuple[str, str]:
    """AI 解析结果的缓存 key。

    key 里带「题目内容 + 用户答案」的内容哈希，好处是**不需要手动删缓存**：
    题干、选项、正确答案、官方解析任意一项被改，哈希就变，自然 miss。
    再加题目 id 是为了方便排查（能直接看出是哪道题）。

    `rag_sig` 是这一步新加的，**非常关键**：接上 RAG 之后，回答依赖
    「检索到了哪些片段」。如果不把它放进 key，会出现两种脏数据：
    - 开 RAG 之前缓存的旧答案（没有任何引用）被当成新答案返回；
    - 知识库更新后，检索结果变了，但缓存还返回旧引用。
    所以 key 里要带上本次命中的 chunk id 列表（或 norag / none）。

    返回 (key, 哈希)，哈希同时用作防击穿锁的名字。
    """
    h = content_hash(
        question.stem,
        question.question_type,
        json.dumps(question.options or [], ensure_ascii=False),
        question.correct_answer,
        question.explanation,
        user_answer,
        rag_sig,
    )
    return f"cuoti:explain:{question.id}:{h}", h


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def sources_event(sources: list[dict], rag_mode: str) -> str:
    """先发一条「引用来源」事件，再流式发正文。

    前端只处理带 `content` 的事件（`if (parsed.content)`），
    所以这条事件对老前端完全无副作用；新前端可以拿它渲染出处。
    """
    return _sse({"sources": sources, "rag_mode": rag_mode})


def replay_cached(text: str, sources: list[dict] | None = None,
                  rag_mode: str = "none"):
    """命中缓存时按同样的事件格式回放，前端不用改代码。

    `cached` 放在最前面：一是让客户端能第一时间知道这是缓存结果，
    二是压测脚本可以只扫每个事件的开头就能判断有没有回源。
    引用来源也要一起回放，否则命中缓存时页面会丢掉出处。
    """
    yield sources_event(sources or [], rag_mode)
    for i in range(0, len(text), REPLAY_CHUNK):
        yield _sse({"cached": True, "content": text[i:i + REPLAY_CHUNK]})
    yield "data: [DONE]\n\n"


@router.post("/explain")
async def ai_explain(
    body: ExplainBody,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """生成题目解析。

    ## 为什么要缓存

    这个接口每次都要调本地大模型（Ollama），单次 2~6 秒；
    而实际使用中大量请求是**同一道高频题**（老师布置的作业题、错题本里的
    重点题会被反复看）。同一道题的解析结果在模型参数不变时是确定的，
    重复调用纯属浪费。

    ## 一致性

    key = 题目id + 题目内容哈希 + 用户答案哈希，写路径改题目内容后
    哈希自然变化，不存在脏读，也不需要为了失效去做 `KEYS` 扫描。

    ## 防击穿

    缓存过期瞬间如果来了 100 个并发请求，直接放行会让 100 个请求同时
    打到 Ollama（本地模型并发能力很差，会集体变慢甚至 OOM）。
    这里用 Redis `SET NX` 互斥锁：抢到锁的唯一一个请求去生成并回填，
    其余请求等待缓存出现后再回放，超时才降级为自己生成。
    """
    question = get_owned_question(body.question_id, user_id, db)

    # ---------- 0. RAG 检索（必须在查缓存之前）----------
    # 因为缓存 key 要包含「本次检索到了哪些片段」，否则知识库一变，
    # 缓存就会返回带旧引用的答案。
    rag_context = ""
    sources: list[dict] = []
    rag_mode = "off"
    rag_sig = "norag"

    if body.use_rag:
        try:
            kp_names = kp_names_for_question(db, question.id)
            query = build_query(question, kp_names)
            rag_result = retrieve(
                db=db, query=query, top_k=body.rag_top_k, alpha=body.rag_alpha,
                ai_api_base=AI_API_BASE,
            )
            hits = rag_result.get("hits") or []
            rag_mode = rag_result.get("mode", "none")
            if hits:
                rag_context, sources = format_context(hits)
                rag_sig = "rag:" + ",".join(str(s.get("chunk_id")) for s in sources)
            else:
                rag_sig = "rag:none"
        except Exception:  # noqa: BLE001
            # 检索挂了不能影响讲解——RAG 是增强，不是前置依赖
            rag_mode = "error"
            rag_sig = "rag:error"

    key, h = explain_cache_key(question, body.user_answer, rag_sig)

    # ---------- 1. 命中缓存直接回放 ----------
    cached = cache.get_json(key)
    if cached and cached.get("text"):
        return StreamingResponse(
            replay_cached(cached["text"], cached.get("sources"), rag_mode),
            media_type="text/event-stream",
        )

    # ---------- 2. 没命中：先抢重建锁（防击穿）----------
    # 必须先用 cache.enabled 短路：缓存不可用时 acquire_lock 永远返回 False，
    # 于是每个请求都会掉进下面的等待分支，白等 CACHE_WAIT_TIMEOUT（120 秒）才生成。
    # 实测这个分支会让"没装 Redis"的环境下每次 AI 解析都卡两分钟。
    lock_name = f"explain:{question.id}:{h}"
    if cache.enabled and not cache.acquire_lock(lock_name, ttl=LOCK_TTL):
        # 关键：等待必须扔到线程池里等。
        # cache.wait_for 内部是 time.sleep 轮询（同步阻塞），
        # 如果直接在 async 函数里调用，会把整个事件循环卡住几十秒——
        # 持锁那个请求的生成器也跟着停摆，缓存永远填不进去，
        # 最后所有请求都超时并各自回源一次，防击穿完全失效。
        filled = await run_in_threadpool(cache.wait_for, key, CACHE_WAIT_TIMEOUT)
        if filled and filled.get("text"):
            return StreamingResponse(
                replay_cached(filled["text"], filled.get("sources"), rag_mode),
                media_type="text/event-stream",
            )
        # 等到超时还没回填（持锁方挂了）：自己生成，但不抢锁、不回填，
        # 避免和持锁方重复写缓存

    # ---------- 3. 回源：调本地模型 ----------
    # 修复：v1 里 context 用 include_answer=True 算出来了，但 system_prompt
    # 又调了一次 build_question_context(include_answer=False)，
    # 结果官方答案和官方解析从来没进过 prompt，模型只能自己瞎猜。
    context = build_question_context(question, include_answer=True)

    user_choice_info = ""
    if body.user_answer:
        user_choice_info = f"\n用户选择的答案是：{body.user_answer}"

    system_prompt = (
        "你是一个专业的错题本 AI 学习助手，帮助用户理解正在练习的题目。\n"
        "回答使用中文，简洁清晰，适合学生理解。\n\n"
        "【当前题目】\n"
        f"{context}\n"
        f"{user_choice_info}\n\n"
        + render_context_block(rag_context)
        + "【工具调用规则 — 必须严格遵守】\n"
        "1. 只有当用户**明确要求查看自己的错题记录**时，才调用 search_wrong_questions。\n"
        "2. 只有当用户**明确给出自己的答案并要求核对**时，才调用 grade_calculation。\n"
        "3. 其他所有情况都直接回答，绝对不要调用任何工具。\n\n"
        "【其他约束】\n"
        "1. 不要直接给出最终答案，除非用户已经提交过答案，或明确要求查看答案。\n"
        "2. 回答中如果用到数学公式，请使用 LaTeX 语法：行内公式用 $...$，块级公式用 $$...$$。"
    )

    client = ollama.Client(host=AI_API_BASE)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请生成解析。"},
    ]

    def stream_and_fill():
        """回源生成，同时把结果写进缓存。

        这里是**同步**生成器，Starlette 会用 `iterate_in_threadpool` 跑它，
        所以里面阻塞的 ollama 调用不会卡住事件循环 —— 这一点是防击穿能生效的前提：
        等待缓存的那些请求才能在这段时间里轮询到结果。
        """
        chunks: list[str] = []
        try:
            # 先把引用来源发给前端，用户能一边等正文一边看到出处
            yield sources_event(sources, rag_mode)
            stream = client.chat(model=AI_MODEL, messages=messages, stream=True)
            for chunk in stream:
                content = chunk.get("message", {}).get("content", "")
                if content:
                    chunks.append(content)
                    yield _sse({"content": content})
            text = "".join(chunks).strip()
            if text:
                cache.set_json(
                    key,
                    {"text": text, "model": AI_MODEL, "sources": sources,
                     "rag_mode": rag_mode},
                    EXPLAIN_TTL,
                )
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield _sse({"error": str(e)})
        finally:
            cache.release_lock(lock_name)

    return StreamingResponse(stream_and_fill(), media_type="text/event-stream")