"""AI 链路的两个安全/正确性回归：锁归属、/chat 错误帧。

对应缺陷：
- P1-5：`/explain` 的防击穿锁没有归属校验 —— 等待缓存超时的那条路径
  在 `finally` 里无条件 `release_lock`，会把**持锁方**的锁删掉，
  于是"同一题同一份输入只调一次模型"的保证被打破。
- P1-8：`/chat` 的错误帧是 `{"type": "error", "content": ...}`，
  前端只判 `parsed.error`，于是"模型调用失败"被当成 AI 的回答渲染出来。
  前端那半在这次一起改了，这里给后端帧格式钉一个契约（前端按 type 判断）。
"""

import json

import pytest

from app.cache import PREFIX, Cache, cache
from app.agent.react import run_react_stream
from app.agent.tools import ToolContext
from app.routes import ai

pytestmark = pytest.mark.usefixtures("client")


class FakeRedis:
    """最小可用的 Redis 替身：只实现缓存层真正用到的那几个命令。"""

    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    def ping(self):
        return True

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        if ex:
            self.ttl[key] = ex
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.data:
                del self.data[key]
                removed += 1
        return removed

    def incrby(self, key, amount=1):
        current = int(self.data.get(key, "0")) + amount
        self.data[key] = str(current)
        return current

    def eval(self, script, numkeys, key, arg):
        # 只支持 cache._RELEASE_LOCK_SCRIPT 这一种脚本
        if self.data.get(key) == arg:
            del self.data[key]
            return 1
        return 0


@pytest.fixture
def fake_redis(monkeypatch):
    """把 cache 换成假 Redis，让锁逻辑在没装 Redis 的机器上也可测。"""
    client = FakeRedis()
    monkeypatch.setattr(cache, "_client", client)
    return client


def _bare_cache(redis_like) -> Cache:
    """构造一个绕过 __init__ 的 Cache 实例（避免真的去连 Redis）。"""
    instance = Cache.__new__(Cache)
    instance.url = "fake://"
    instance.timeout = 0.1
    instance._client = redis_like
    instance._local = {"hit": 0, "miss": 0, "error": 0, "bypass": 0}
    return instance


# ============================================================
# 锁归属
# ============================================================

def test_acquire_lock_returns_owner_token_and_is_exclusive(fake_redis):
    first = cache.acquire_lock("unit:lock", ttl=30)
    assert first and isinstance(first, str)
    assert cache.acquire_lock("unit:lock", ttl=30) is None


def test_release_lock_with_wrong_owner_keeps_lock(fake_redis):
    owner = cache.acquire_lock("unit:lock", ttl=30)
    assert cache.release_lock("unit:lock", "someone-else") is False
    assert fake_redis.data[f"{PREFIX}:lock:unit:lock"] == owner


def test_release_lock_with_owner_removes_lock(fake_redis):
    owner = cache.acquire_lock("unit:lock", ttl=30)
    assert cache.release_lock("unit:lock", owner) is True
    assert f"{PREFIX}:lock:unit:lock" not in fake_redis.data
    # 释放后别人能立刻抢到，且拿到的是新 token
    again = cache.acquire_lock("unit:lock", ttl=30)
    assert again and again != owner


def test_release_lock_without_owner_does_not_touch_token_locks(fake_redis):
    """旧调用方（不传 owner）不能误删用 token 持有的锁。"""
    owner = cache.acquire_lock("unit:lock", ttl=30)
    assert cache.release_lock("unit:lock") is False
    assert fake_redis.data[f"{PREFIX}:lock:unit:lock"] == owner


def test_release_lock_without_owner_still_clears_legacy_marker(fake_redis):
    """早期版本把锁值写成 "1"，这种锁仍然可以被无 owner 的旧调用清理。"""
    fake_redis.data[f"{PREFIX}:lock:legacy"] = "1"
    assert cache.release_lock("legacy") is True
    assert f"{PREFIX}:lock:legacy" not in fake_redis.data


# ============================================================
# /explain：等待超时的请求不许删持锁方的锁
# ============================================================

class FakeChatClient:
    """假模型：一次流式返回固定文本，不碰网络。"""

    def __init__(self, text="这是一段解析。"):
        self.text = text
        self.calls = 0

    def chat(self, model, messages, stream=True, **kwargs):
        self.calls += 1
        return iter([{"message": {"content": self.text}}])


@pytest.fixture
def explain_env(fake_redis, monkeypatch, sample_question):
    """把 /explain 的外部依赖全换成假的，并返回关键句柄。"""
    chat_client = FakeChatClient()
    monkeypatch.setattr(ai, "get_chat_client", lambda: chat_client)
    # 锁定 key 里的内容哈希，避免依赖题目字段的全部细节
    monkeypatch.setattr(ai, "explain_cache_key", lambda *a, **k: ("fake:explain:key", "h"))
    # 等待缓存的时间压到 0.05s，否则用例要等两分钟
    monkeypatch.setattr(ai, "CACHE_WAIT_TIMEOUT", 0.05)
    return {
        "client": chat_client,
        "question_id": sample_question["id"],
        "cache_key": "fake:explain:key",
        "lock_key": f"{PREFIX}:lock:explain:{sample_question['id']}:h",
    }


def _explain(client, auth_headers, question_id):
    return client.post(
        "/api/ai/explain",
        json={"question_id": question_id, "user_answer": "B", "use_rag": False},
        headers=auth_headers,
    )


def test_explain_keeps_foreign_lock_when_wait_times_out(explain_env, fake_redis, client, auth_headers):
    """核心回归：没抢到锁 → 等超时 → 自己生成，但**不能**删别人的锁。"""
    foreign = "foreign-owner-token"
    fake_redis.data[explain_env["lock_key"]] = foreign

    resp = _explain(client, auth_headers, explain_env["question_id"])
    assert resp.status_code == 200, resp.text
    assert "这是一段解析。" in resp.text

    assert fake_redis.data.get(explain_env["lock_key"]) == foreign, (
        "等待超时的请求把持锁方的锁删掉了，防击穿窗口被重新打开"
    )


def test_explain_releases_own_lock_after_generating(explain_env, fake_redis, client, auth_headers):
    resp = _explain(client, auth_headers, explain_env["question_id"])
    assert resp.status_code == 200, resp.text
    # 自己抢到锁 → 生成完必须释放，否则下一次解析会被锁挡住 180s
    assert explain_env["lock_key"] not in fake_redis.data


def test_explain_replays_cached_text_without_calling_model(explain_env, fake_redis, client, auth_headers):
    fake_redis.data[explain_env["cache_key"]] = json.dumps(
        {"text": "缓存里的解析。", "model": "fake", "sources": [], "rag_mode": "off"},
        ensure_ascii=False,
    )
    resp = _explain(client, auth_headers, explain_env["question_id"])
    assert resp.status_code == 200
    assert "缓存里的解析。" in resp.text
    assert explain_env["client"].calls == 0


# ============================================================
# /chat 的 SSE 帧契约（前端按 type 判断）
# ============================================================

def _frames(raw: str) -> list[dict]:
    out = []
    for line in raw.split("\n\n"):
        line = line.strip()
        if line.startswith("data: "):
            payload = line[len("data: "):]
            if payload == "[DONE]":
                continue
            out.append(json.loads(payload))
    return out


def _tool_context(db) -> ToolContext:
    return ToolContext(db=db, user_id=1)


def test_chat_stream_emits_typed_text_frame(db):
    client_ok = FakeChatClient("答案是 B。")
    raw = "".join(
        run_react_stream(
            client=client_ok,
            model="fake",
            system_prompt="sys",
            user_messages=[{"role": "user", "content": "这题怎么做"}],
            tools_schema=[],
            tool_context=_tool_context(db),
        )
    )
    frames = _frames(raw)
    assert {"type": "text", "content": "答案是 B。"} in frames
    assert frames[-1] == {"type": "done"}


def test_chat_stream_emits_typed_error_frame_when_model_fails(db):
    class Boom:
        def chat(self, *a, **k):
            raise RuntimeError("连接被拒绝")

    raw = "".join(
        run_react_stream(
            client=Boom(),
            model="fake",
            system_prompt="sys",
            user_messages=[{"role": "user", "content": "这题怎么做"}],
            tools_schema=[],
            tool_context=_tool_context(db),
        )
    )
    frames = _frames(raw)
    assert frames and frames[0]["type"] == "error"
    assert "模型调用失败" in frames[0]["content"]
    # 错误帧必须带 type，前端才分得清"回答"和"错误"
    assert "content" in frames[0]
