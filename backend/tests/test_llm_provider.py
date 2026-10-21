"""模型接入层的测试（不联网）。

重点验证「百炼适配器和 ollama 客户端形状一致」这件事，因为上层的 ReAct 循环、
打标器、解析接口全都按 ollama 的返回形状写的。一旦形状不对，
表现是线上才炸的空指针。

用 `httpx.MockTransport` 模拟百炼的响应，所以这些用例不需要真 key、不发真实请求。
"""

import json

import httpx
import pytest

from app import llm
from app.llm import BailianChatClient, LLMError, describe


# ============================================================
# 工具函数
# ============================================================

def make_client(handler, key="sk-test-key-1234567890"):
    """构造一个把 httpx.post / httpx.stream 换成假实现的客户端。"""
    client = BailianChatClient(api_key=key)
    transport = httpx.MockTransport(handler)

    # 把模块级的 httpx.post / httpx.stream 换掉
    class PatchedHTTPX:
        @staticmethod
        def post(url, **kwargs):
            with httpx.Client(transport=transport) as c:
                return c.post(url, **kwargs)

        @staticmethod
        def stream(method, url, **kwargs):
            c = httpx.Client(transport=transport)
            return c.stream(method, url, **kwargs)

        HTTPError = httpx.HTTPError

    return client, PatchedHTTPX


def sse_lines(*chunks) -> bytes:
    body = b""
    for ch in chunks:
        body += b"data: " + json.dumps(ch, ensure_ascii=False).encode() + b"\n\n"
    body += b"data: [DONE]\n\n"
    return body


# ============================================================
# 配置
# ============================================================

def test_client_requires_key(monkeypatch):
    with pytest.raises(LLMError, match="BAILIAN_API_KEY"):
        BailianChatClient(api_key="")


def test_describe_does_not_leak_key(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "bailian")
    monkeypatch.setattr(llm, "BAILIAN_API_KEY", "sk-secret-should-not-appear")
    info = describe()
    assert info["provider"] == "bailian"
    dumped = json.dumps(info, ensure_ascii=False)
    assert "sk-secret" not in dumped
    assert info["api_key_configured"] is True


def test_model_name_follows_provider(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "bailian")
    assert llm.chat_model() == llm.BAILIAN_MODEL
    assert llm.embed_model() == llm.BAILIAN_EMBED_MODEL

    monkeypatch.setattr(llm, "PROVIDER", "ollama")
    assert llm.chat_model() == llm.OLLAMA_MODEL
    assert llm.embed_model() == llm.OLLAMA_EMBED_MODEL


# ============================================================
# 非流式对话
# ============================================================

def test_chat_once_returns_ollama_shape(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "这是解析。"}}],
            "usage": {"total_tokens": 42},
        })

    client, fake = make_client(handler)
    monkeypatch.setattr(llm.httpx, "post", fake.post)

    resp = client.chat(model="qwen-plus",
                       messages=[{"role": "user", "content": "hi"}])

    # 形状必须和 ollama 一致：{"message": {"content": ...}}
    assert resp["message"]["content"] == "这是解析。"
    assert resp["message"]["tool_calls"] == []
    assert captured["url"].endswith("/chat/completions")
    assert captured["auth"] == "Bearer sk-test-key-1234567890"
    assert captured["body"]["model"] == "qwen-plus"
    assert captured["body"]["stream"] is False


def test_chat_maps_format_json_to_response_format(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"items":[]}'}}],
        })

    client, fake = make_client(handler)
    monkeypatch.setattr(llm.httpx, "post", fake.post)

    client.chat(messages=[{"role": "user", "content": "x"}],
                format="json", options={"temperature": 0.1})

    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["temperature"] == 0.1


def test_chat_error_mentions_key_hint(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid API-key"}})

    client, fake = make_client(handler)
    monkeypatch.setattr(llm.httpx, "post", fake.post)

    with pytest.raises(LLMError) as exc:
        client.chat(messages=[{"role": "user", "content": "x"}])
    assert "401" in str(exc.value)
    assert "key" in str(exc.value).lower()


def test_chat_error_mentions_model_hint(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "model not found"}})

    client, fake = make_client(handler)
    monkeypatch.setattr(llm.httpx, "post", fake.post)

    with pytest.raises(LLMError) as exc:
        client.chat(messages=[{"role": "user", "content": "x"}])
    assert "模型名" in str(exc.value)


# ============================================================
# 流式对话 + 工具调用分片
# ============================================================

def test_chat_stream_yields_content_chunks(monkeypatch):
    body = sse_lines(
        {"choices": [{"delta": {"content": "你"}}]},
        {"choices": [{"delta": {"content": "好"}}]},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body,
                              headers={"content-type": "text/event-stream"})

    client, fake = make_client(handler)
    monkeypatch.setattr(llm.httpx, "stream", fake.stream)

    chunks = list(client.chat(messages=[{"role": "user", "content": "x"}], stream=True))
    text = "".join(c.get("message", {}).get("content", "") for c in chunks)
    assert text == "你好"


def test_chat_stream_reassembles_split_tool_calls(monkeypatch):
    """百炼的工具调用是分片到达的：先 name，再一段段 arguments。

    ReAct 循环只认「一次完整的 tool_calls」，所以适配器必须自己拼起来。
    这是最容易写错的地方——拼错了工具参数就是残缺的 JSON。
    """
    body = sse_lines(
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_abc", "function": {"name": "search_wrong_questions"}}
        ]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"key'}}
        ]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": 'word":"二次函数"}'}}
        ]}}]},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    client, fake = make_client(handler)
    monkeypatch.setattr(llm.httpx, "stream", fake.stream)

    chunks = list(client.chat(messages=[{"role": "user", "content": "x"}], stream=True))
    tool_chunks = [c for c in chunks if c["message"].get("tool_calls")]
    assert len(tool_chunks) == 1, "工具调用应该在最后合成一个完整事件"

    tc = tool_chunks[0]["message"]["tool_calls"][0]
    assert tc["function"]["name"] == "search_wrong_questions"
    assert json.loads(tc["function"]["arguments"]) == {"keyword": "二次函数"}
    assert tc["id"] == "call_abc"


def test_chat_once_normalizes_tool_calls(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "",
            "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "grade_calculation", "arguments": '{"a":1}'},
            }],
        }}]})

    client, fake = make_client(handler)
    monkeypatch.setattr(llm.httpx, "post", fake.post)

    resp = client.chat(messages=[{"role": "user", "content": "x"}])
    tc = resp["message"]["tool_calls"][0]
    assert tc["function"]["name"] == "grade_calculation"
    assert tc["id"] == "call_1"


# ============================================================
# 向量
# ============================================================

def test_bailian_embedder_batches_and_orders(monkeypatch):
    from app.rag.embedder import BailianEmbedder

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        # 故意倒序返回，验证适配器会按 index 排回去
        data = [
            {"index": i, "embedding": [float(i)] * 3}
            for i in reversed(range(len(payload["input"])))
        ]
        return httpx.Response(200, json={"data": data})

    embedder = BailianEmbedder(api_key="sk-test", batch_size=2)
    monkeypatch.setattr(
        llm.httpx, "post",
        lambda url, **kw: httpx.Client(transport=httpx.MockTransport(handler)).post(url, **kw),
    )

    vecs = embedder.embed(["a", "b", "c"])
    assert len(vecs) == 3
    assert vecs[0][0] == 0.0 and vecs[2][0] == 0.0   # 每批内部按 index 归位
    assert len(calls) == 2                           # 3 条按 2 一批 -> 2 次请求
    assert calls[0]["input"] == ["a", "b"]


def test_bailian_embedder_without_key():
    from app.rag.embedder import BailianEmbedder

    embedder = BailianEmbedder(api_key="")
    assert embedder.available() is False
    with pytest.raises(RuntimeError, match="BAILIAN_API_KEY"):
        embedder.embed(["x"])


def test_get_embedder_picks_provider(monkeypatch):
    from app.rag import embedder as emb

    monkeypatch.setattr(emb, "PROVIDER", "bailian")
    monkeypatch.setattr(emb, "BAILIAN_API_KEY", "sk-test")
    got = emb.get_embedder()
    assert isinstance(got, emb.BailianEmbedder)

    monkeypatch.setattr(emb, "BAILIAN_API_KEY", "")
    assert emb.get_embedder() is None


# ============================================================
# ReAct 兼容性
# ============================================================

def test_react_passes_tool_call_id(monkeypatch):
    """ReAct 回传工具结果时必须带 tool_call_id，否则百炼会 400。"""
    from app.agent.react import run_react_stream
    from app.agent.tools import ToolContext

    class FakeClient:
        def __init__(self):
            self.rounds = 0
            self.seen_messages = []

        def chat(self, **kwargs):
            self.seen_messages.append(kwargs["messages"])
            self.rounds += 1
            if self.rounds == 1:
                return iter([{"message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_xyz", "type": "function",
                        "function": {"name": "search_wrong_questions",
                                     "arguments": '{"limit":1}'},
                    }],
                }}])
            return iter([{"message": {"content": "好了"}}])

    class FakeDB:
        def query(self, *a, **k):
            raise AssertionError("不该真的查库")

    client = FakeClient()
    list(run_react_stream(
        client=client, model="m", system_prompt="s",
        user_messages=[{"role": "user", "content": "找错题"}],
        tools_schema=[], tool_context=ToolContext(db=FakeDB(), user_id=1),
    ))

    # 第二轮请求里，tool 消息必须带 tool_call_id
    second_round = client.seen_messages[1]
    tool_msgs = [m for m in second_round if m.get("role") == "tool"]
    assert tool_msgs, "应该回传了一次工具结果"
    assert tool_msgs[0].get("tool_call_id") == "call_xyz"

    # assistant 消息里的 tool_calls 也要带 id
    assistant = [m for m in second_round if m.get("role") == "assistant"
                 and m.get("tool_calls")]
    assert assistant[0]["tool_calls"][0]["id"] == "call_xyz"
