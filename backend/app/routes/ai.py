"""AI 助手与 AI 解析接口。

- /chat：走 ReAct 循环，模型可调用工具（错题检索、批改）
- /explain：单轮，直接生成解析（不需要工具）
"""

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import ollama

from app.agent.react import run_react_stream
from app.agent.tools import TOOLS_SCHEMA, ToolContext
from app.db import get_db
from app.models import Question, QuestionBank
from app.routes.banks import current_user_id

router = APIRouter(prefix="/api/ai", tags=["ai"])

AI_API_BASE = os.getenv("AI_API_BASE", "http://localhost:11434")
AI_MODEL = os.getenv("AI_MODEL", "qwen2.5:7b")


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatBody(BaseModel):
    question_id: int
    messages: list[ChatMessage]


class ExplainBody(BaseModel):
    question_id: int
    user_answer: str = ""


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
# AI 解析（单轮，无工具）
# ============================================================

@router.post("/explain")
async def ai_explain(
    body: ExplainBody,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    question = get_owned_question(body.question_id, user_id, db)

    context = build_question_context(question, include_answer=True)

    user_choice_info = ""
    if body.user_answer:
        user_choice_info = f"\n用户选择的答案是：{body.user_answer}"

    system_prompt = (
        "你是一个专业的错题本 AI 学习助手，帮助用户理解正在练习的题目。\n"
        "回答使用中文，简洁清晰，适合学生理解。\n\n"
        "【当前题目】\n"
        f"{build_question_context(question, include_answer=False)}\n\n"
        "【可用工具】\n"
        "- search_wrong_questions：查询该用户答错过的题目列表。\n"
        "- grade_calculation：批改该用户对某道计算/简答/填空题的作答。\n\n"
        "【工具调用规则 — 必须严格遵守】\n"
        "1. 只有当用户**明确要求查看自己的错题记录**时（例如：“我错过哪些题”、“我之前做错了什么”、“帮我找找错题”），才调用 search_wrong_questions。\n"
        "2. 只有当用户**明确给出自己的答案并要求核对**时（例如：“我算的答案是 X，对吗”、“帮我看看这道题做对没”），才调用 grade_calculation。\n"
        "3. 其他所有情况（包括问知识点、问解题思路、问公式、闲聊、问概念），**都直接回答，绝对不要调用任何工具**。\n"
        "4. 不确定是否要调用工具时，**默认不调用**，直接回答用户问题。\n\n"
        "【工具结果处理规则】\n"
        "1. 当你收到 tool 消息（工具执行结果）后，**必须基于该结果回答用户最初提出的问题**，不要跑题。\n"
        "2. 如果工具返回了错题列表，你要把结果整理成用户能读的清单。\n"
        "3. 如果工具返回了批改结果，你要明确告诉用户“对”或“错”，并说明正确答案是什么。\n\n"
        "【其他约束】\n"
        "1. 不要直接给出最终答案，除非用户已经提交过答案，或明确要求查看答案。\n"
        "2. 回答中如果用到数学公式，请使用 LaTeX 语法：行内公式用 $...$，块级公式用 $$...$$。"
    )

    client = ollama.Client(host=AI_API_BASE)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请生成解析。"},
    ]

    def stream():
        try:
            s = client.chat(model=AI_MODEL, messages=messages, stream=True)
            for chunk in s:
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield f"data: {__import__('json').dumps({'content': content}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {__import__('json').dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")