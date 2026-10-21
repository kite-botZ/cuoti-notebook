"""模型服务自检：确认 key / 模型名 / 网络都通，并测一下真实耗时。

用法（先把 key 写进 backend/.env，不要提交到仓库）：

    cd backend
    python scripts/check_llm.py

它会依次检查 5 项：

1. 配置是否完整（provider、模型名、key 有没有读到）
2. **对话**接口能不能通（AI 解析依赖）
3. **JSON 输出**能不能通（知识点打标依赖）
4. **工具调用**能不能通（AI 助手 / ReAct 依赖）
5. **向量**接口能不能通（RAG 语义检索依赖），并检查维度与相似度是否合理

任何一项失败都会打印出接口返回的原文，方便判断是 key 错、模型名错还是欠费。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def mask(key: str) -> str:
    if not key:
        return "(未配置)"
    if len(key) <= 12:
        return key[:3] + "***"
    return f"{key[:6]}…{key[-4:]}（共 {len(key)} 位）"


def main() -> int:
    os.environ.setdefault("APP_ENV", "development")
    sys.path.insert(0, str(BACKEND_DIR))

    # 读 .env，这样不用手动设环境变量
    try:
        from dotenv import load_dotenv
        load_dotenv(BACKEND_DIR / ".env")
        load_dotenv(BACKEND_DIR.parent / ".env")
    except Exception:  # noqa: BLE001
        pass

    from app import llm

    print("=" * 68)
    print("① 配置")
    print(f"   LLM_PROVIDER   = {llm.PROVIDER}")
    if llm.PROVIDER == "bailian":
        print(f"   BAILIAN_BASE_URL = {llm.BAILIAN_BASE_URL}")
        print(f"   BAILIAN_MODEL    = {llm.BAILIAN_MODEL}")
        print(f"   BAILIAN_EMBED    = {llm.BAILIAN_EMBED_MODEL}")
        print(f"   BAILIAN_API_KEY  = {mask(llm.BAILIAN_API_KEY)}")
    else:
        print(f"   AI_API_BASE    = {llm.OLLAMA_BASE}")
        print(f"   AI_MODEL       = {llm.OLLAMA_MODEL}")
        print(f"   EMBED_MODEL    = {llm.OLLAMA_EMBED_MODEL}")

    if llm.PROVIDER == "bailian" and not llm.BAILIAN_API_KEY:
        print("\n❌ BAILIAN_API_KEY 没读到。检查 backend/.env 里有没有这一行，"
              "以及文件编码是不是 UTF-8。")
        return 2

    ok = True

    # ---------- ② 对话 ----------
    print("\n② 对话接口")
    try:
        client = llm.get_chat_client()
        started = time.perf_counter()
        resp = client.chat(
            model=llm.chat_model(),
            messages=[{"role": "user", "content": "用一句二十字以内的话说明什么是错题本。"}],
        )
        cost = time.perf_counter() - started
        content = (resp.get("message") or {}).get("content", "").strip()
        print(f"   ✅ {cost:.2f}s  返回：{content[:60]}")
        usage = resp.get("usage") or {}
        if usage:
            print(f"      token 用量：{usage}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"   ❌ 失败：{e}")

    # ---------- ③ JSON 输出（打标依赖）----------
    print("\n③ JSON 输出（知识点打标依赖）")
    try:
        client = llm.get_chat_client()
        resp = client.chat(
            model=llm.chat_model(),
            messages=[{
                "role": "user",
                "content": '给这道题打知识点，只输出 JSON：'
                           '{"items":[{"id":1,"knowledge_points":[{"name":"...","weight":1.0}]}]}\n'
                           '题目：下列哪个是编程语言？A. Python B. HTML',
            }],
            format="json",
            options={"temperature": 0.1},
        )
        raw = (resp.get("message") or {}).get("content", "").strip()
        import json
        try:
            json.loads(raw)
            print(f"   ✅ 返回合法 JSON：{raw[:80]}")
        except ValueError:
            ok = False
            print(f"   ⚠ 返回的不是合法 JSON（打标会失败）：{raw[:120]}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"   ❌ 失败：{e}")

    # ---------- ④ 工具调用（ReAct 依赖）----------
    print("\n④ 工具调用（AI 助手依赖）")
    tools = [{
        "type": "function",
        "function": {
            "name": "search_wrong_questions",
            "description": "搜索用户答错过的题目",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string"}},
                "required": [],
            },
        },
    }]
    try:
        client = llm.get_chat_client()
        resp = client.chat(
            model=llm.chat_model(),
            messages=[{"role": "user",
                       "content": "帮我找找我之前错过哪些关于二次函数的题"}],
            tools=tools,
        )
        msg = resp.get("message") or {}
        calls = msg.get("tool_calls") or []
        if calls:
            fn = calls[0].get("function") or {}
            print(f"   ✅ 模型正确发起工具调用：{fn.get('name')} "
                  f"参数 {fn.get('arguments')}  id={calls[0].get('id')}")
        else:
            print(f"   ⚠ 模型没有发起工具调用（也能用，只是 AI 助手不会查错题）"
                  f"  返回：{str(msg.get('content'))[:60]}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"   ❌ 失败：{e}")

    # ---------- ⑤ 向量 ----------
    print("\n⑤ 向量接口（RAG 语义检索依赖）")
    try:
        from app.rag.embedder import get_embedder
        embedder = get_embedder()
        if embedder is None:
            ok = False
            print("   ❌ 拿不到向量器（key 未配置，或模型不可用）")
        else:
            texts = ["中心理解题要先看问题再划分层次", "图形推理要看位置和样式规律"]
            started = time.perf_counter()
            vecs = embedder.embed(texts)
            cost = time.perf_counter() - started
            dim = len(vecs[0]) if vecs else 0
            print(f"   ✅ {cost:.2f}s  模型 {embedder.model}  维度 {dim}")
            if dim and len(vecs) == len(texts):
                from app.rag.embedder import cosine
                sim_self = cosine(vecs[0], vecs[0])
                sim_cross = cosine(vecs[0], vecs[1])
                print(f"      自相似度 {sim_self:.3f}（应≈1.0）  "
                      f"跨主题相似度 {sim_cross:.3f}（应明显更低）")
                if sim_self < 0.99:
                    print("      ⚠ 自相似度不正常，向量可能有问题")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"   ❌ 失败：{e}")

    print("\n" + "=" * 68)
    if ok:
        print("结论：全部通过，可以直接用。")
        print("如果要立刻启用向量检索，重新灌一遍知识库（旧片段没有向量）：")
        print("  python scripts/ingest_docs.py <讲义目录> --subject 行测 --force")
    else:
        print("结论：有失败项，先按上面的报错排查，再重启后端。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
