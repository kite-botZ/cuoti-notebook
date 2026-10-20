"""RAG 接入 AI 解析的测试。

这一步要验证的是「检索到的教材片段真的被用上了」，以及几个容易出错的地方：

- **引用编号不能错位**：prompt 里的 `[1]` 必须对应 `sources[0]`；
- **没有检索结果时不能硬塞引用**：否则模型会编造「教材说……」；
- **缓存 key 必须包含检索结果**：不然知识库更新后，用户还在看旧引用；
- **检索失败不能拖垮讲解**：RAG 是增强，不是前置依赖；
- **关掉 use_rag 就完全不走检索**。
"""

import json

import pytest

from app.cache import cache
from app.models import DocumentChunk, KnowledgeDocument
from app.rag.context import (
    build_query,
    format_context,
    kp_names_for_question,
    render_context_block,
)
from app.routes.ai import explain_cache_key


# ============================================================
# 上下文构造
# ============================================================

class FakeQuestion:
    def __init__(self, stem="中心理解题的总原则是什么？",
                 options=("甲", "乙", "丙"), correct_answer="A",
                 explanation="先看问题", question_type="single", qid=1):
        self.id = qid
        self.stem = stem
        self.options = list(options)
        self.correct_answer = correct_answer
        self.explanation = explanation
        self.question_type = question_type


def test_build_query_puts_kp_names_first():
    q = FakeQuestion()
    query = build_query(q, ["中心理解题", "主体一致"])
    assert query.startswith("中心理解题 主体一致")
    assert "中心理解题的总原则" in query
    assert "甲" in query


def test_build_query_without_kp():
    query = build_query(FakeQuestion(), None)
    assert "中心理解题的总原则" in query


def test_build_query_is_capped():
    q = FakeQuestion(stem="长" * 2000)
    assert len(build_query(q)) <= 400


def test_format_context_numbering_matches_sources():
    hits = [
        {"chunk_id": 11, "doc_id": 1, "title": "言语理解笔记", "chapter": "一、中心理解题",
         "page": 3, "text": "总原则是先看问题。", "score": 0.9},
        {"chunk_id": 12, "doc_id": 1, "title": "言语理解笔记", "chapter": "二、细节判断",
         "page": 8, "text": "细节题要回原文比对。", "score": 0.7},
    ]
    context, sources = format_context(hits)

    assert context.startswith("[1] 《言语理解笔记》")
    assert "[2] " in context
    assert sources[0]["index"] == 1 and sources[0]["chunk_id"] == 11
    assert sources[1]["index"] == 2 and sources[1]["chunk_id"] == 12
    assert sources[0]["page"] == 3


def test_format_context_empty():
    assert format_context([]) == ("", [])


def test_format_context_respects_budget():
    hits = [
        {"chunk_id": i, "doc_id": 1, "title": "T", "chapter": "", "page": None,
         "text": "字" * 380, "score": 0.5}
        for i in range(10)
    ]
    context, sources = format_context(hits)
    assert len(context) <= 1400
    assert len(sources) < 10          # 预算用完就不再收


def test_render_context_block_includes_rules():
    block = render_context_block("[1] 《教材》\n正文")
    assert "教材参考片段" in block
    assert "引用规则" in block
    assert "不要整段照抄" in block


def test_render_context_block_empty_when_no_context():
    assert render_context_block("") == ""


# ============================================================
# 缓存 key
# ============================================================

def test_cache_key_changes_with_rag_signature():
    q = FakeQuestion()
    k_norag, _ = explain_cache_key(q, "A", "norag")
    k_rag1, _ = explain_cache_key(q, "A", "rag:11,12")
    k_rag2, _ = explain_cache_key(q, "A", "rag:11,13")
    assert len({k_norag, k_rag1, k_rag2}) == 3


def test_cache_key_stable_for_same_signature():
    q = FakeQuestion()
    assert explain_cache_key(q, "A", "rag:11")[0] == explain_cache_key(q, "A", "rag:11")[0]


# ============================================================
# 接口端到端（假的 Ollama 客户端）
# ============================================================

TEXTBOOK = """一、中心理解题
总原则：先看问题，再用句号划分层次，理清脉络层次。主体一致、话题一致、符合题干。
首句圈出主语，要讲的话题通常在首句。关联词转折之后是重点。

二、细节判断题
细节判断题要回原文逐句比对，注意偷换概念和无中生有。
"""


def fake_ollama_client(text="先看问题再找主体。[1]"):
    """构造一个假的 ollama 模块级 Client。"""

    class FakeClient:
        def __init__(self, host=None, **kwargs):
            pass

        def chat(self, model=None, messages=None, stream=False, **kwargs):
            # 记录拿到的 system prompt，供断言检查
            FakeClient.last_messages = messages
            return iter([{"message": {"content": text}}])

    return FakeClient


def _seed_doc(client, auth_headers, monkeypatch, subject="行测"):
    """往知识库塞一份教材（用不依赖 Ollama 的降级模式）。"""
    monkeypatch.setattr("app.rag.service.get_embedder", lambda *a, **k: None)
    resp = client.post(
        "/api/knowledge-docs",
        files={"file": ("言语.md", TEXTBOOK.encode(), "text/markdown")},
        data={"title": "言语理解笔记", "subject": subject},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "ready"
    return resp.json()


def _create_question(client, auth_headers, bank_id, stem="中心理解题的总原则是什么？"):
    resp = client.post(
        f"/api/banks/{bank_id}/questions",
        json={"stem": stem, "question_type": "single",
              "options": ["甲", "乙"], "correct_answer": "A", "explanation": ""},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def parse_sse(raw: str) -> list:
    """把 SSE 响应解析成事件列表。"""
    events = []
    for line in raw.split("\n\n"):
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            continue
        try:
            events.append(json.loads(payload))
        except ValueError:
            continue
    return events


def test_explain_emits_sources_from_rag(client, auth_headers, created_bank, monkeypatch):
    _seed_doc(client, auth_headers, monkeypatch)
    qid = _create_question(client, auth_headers, created_bank["id"])

    import ollama
    monkeypatch.setattr(ollama, "Client", fake_ollama_client())

    resp = client.post("/api/ai/explain",
                       json={"question_id": qid, "user_answer": "B"},
                       headers=auth_headers)
    assert resp.status_code == 200
    events = parse_sse(resp.text)

    source_events = [e for e in events if "sources" in e]
    assert source_events, "应该先发一条引用来源事件"
    sources = source_events[0]["sources"]
    assert sources, "知识库里明明有相关内容，应该检索到"
    assert sources[0]["title"] == "言语理解笔记"
    assert source_events[0]["rag_mode"] in ("bm25", "hybrid", "vector")

    # 正文也被流式发出来了
    content = "".join(e.get("content", "") for e in events)
    assert content


def test_explain_prompt_contains_textbook_context(client, auth_headers, created_bank, monkeypatch):
    _seed_doc(client, auth_headers, monkeypatch)
    qid = _create_question(client, auth_headers, created_bank["id"])

    import ollama
    fake = fake_ollama_client()
    monkeypatch.setattr(ollama, "Client", fake)

    client.post("/api/ai/explain", json={"question_id": qid},
                headers=auth_headers)

    # 检查真正发给模型的 prompt 里有没有教材上下文和引用规则
    messages = fake.last_messages
    system = messages[0]["content"]
    assert "【教材参考片段】" in system
    assert "引用规则" in system
    assert "言语理解笔记" in system


def test_explain_without_docs_has_empty_sources(client, auth_headers, created_bank, monkeypatch):
    """知识库是空的：不能凭空造引用。"""
    qid = _create_question(client, auth_headers, created_bank["id"])
    import ollama
    fake = fake_ollama_client("直接讲题。[1]")
    monkeypatch.setattr(ollama, "Client", fake)

    resp = client.post("/api/ai/explain", json={"question_id": qid},
                       headers=auth_headers)
    events = parse_sse(resp.text)
    sources = [e for e in events if "sources" in e][0]["sources"]
    assert sources == []
    # 没有上下文时，prompt 里不应出现「教材参考片段」
    assert "【教材参考片段】" not in fake.last_messages[0]["content"]


def test_explain_use_rag_false_skips_retrieval(client, auth_headers, created_bank, monkeypatch):
    _seed_doc(client, auth_headers, monkeypatch)
    qid = _create_question(client, auth_headers, created_bank["id"])

    import ollama
    fake = fake_ollama_client()
    monkeypatch.setattr(ollama, "Client", fake)

    resp = client.post("/api/ai/explain",
                       json={"question_id": qid, "use_rag": False},
                       headers=auth_headers)
    events = parse_sse(resp.text)
    source_events = [e for e in events if "sources" in e]
    assert source_events[0]["sources"] == []
    assert source_events[0]["rag_mode"] == "off"
    assert "【教材参考片段】" not in fake.last_messages[0]["content"]


def test_explain_survives_rag_failure(client, auth_headers, created_bank, monkeypatch):
    """检索层抛异常时，讲解必须照常返回（RAG 是增强不是依赖）。"""
    qid = _create_question(client, auth_headers, created_bank["id"])

    def boom(*args, **kwargs):
        raise RuntimeError("向量库炸了")

    monkeypatch.setattr("app.routes.ai.retrieve", boom)
    import ollama
    fake = fake_ollama_client("照常讲课。")
    monkeypatch.setattr(ollama, "Client", fake)

    resp = client.post("/api/ai/explain", json={"question_id": qid},
                       headers=auth_headers)
    assert resp.status_code == 200
    events = parse_sse(resp.text)
    assert [e for e in events if "sources" in e][0]["rag_mode"] == "error"
    assert "".join(e.get("content", "") for e in events).strip()


@pytest.mark.skipif(not cache.enabled, reason="缓存回放需要可用的 Redis")
def test_cached_replay_keeps_sources(client, auth_headers, created_bank, monkeypatch):
    """命中缓存时，引用来源也要一起回放，否则页面会丢掉出处。"""
    _seed_doc(client, auth_headers, monkeypatch)
    qid = _create_question(client, auth_headers, created_bank["id"])

    import ollama
    monkeypatch.setattr(ollama, "Client", fake_ollama_client())

    first = client.post("/api/ai/explain", json={"question_id": qid},
                        headers=auth_headers)
    first_sources = [e for e in parse_sse(first.text) if "sources" in e][0]["sources"]

    second = client.post("/api/ai/explain", json={"question_id": qid},
                         headers=auth_headers)
    events = parse_sse(second.text)
    second_sources = [e for e in events if "sources" in e][0]["sources"]

    assert second_sources == first_sources
    assert second_sources, "缓存回放也应该带出处"
    # 第二次应该是缓存命中
    assert any(e.get("cached") for e in events)


def test_kp_names_are_used_in_query(client, auth_headers, created_bank, db):
    """题目有知识点标签时，检索查询应该带上知识点名称。"""
    qid = _create_question(client, auth_headers, created_bank["id"])
    client.put(f"/api/questions/{qid}/knowledge-points",
               json={"knowledge_points": [{"name": "中心理解题", "weight": 1.0}]},
               headers=auth_headers)

    names = kp_names_for_question(db, qid)
    assert names == ["中心理解题"]

    from app.models import Question
    q = db.query(Question).filter(Question.id == qid).first()
    assert build_query(q, names).startswith("中心理解题")
