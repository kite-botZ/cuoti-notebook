"""大模型接入层：本地 Ollama 或 阿里云百炼（DashScope 的 OpenAI 兼容模式）。

## 为什么要有这一层

调用大模型的地方有 4 处：AI 解析、AI 助手（ReAct）、知识点打标、向量化。
如果每处都写 `if provider == "bailian": ... else: ...`，换模型时一定改漏。

## 适配器的关键设计

`BailianChatClient` **刻意做成和 `ollama.Client` 一样的调用形状**：
`chat(model=..., messages=..., stream=..., tools=..., format=...)`，
连返回值都是 `{"message": {"content": ..., "tool_calls": [...]}}`。

这样上层的 ReAct 循环和打标器一行都不用改——它们不知道自己连的是本地模型还是云 API。

## 为什么不装 openai SDK

百炼的兼容模式就是标准 HTTP + Bearer Token，用 httpx 直接发请求即可。
少一个依赖，也少一层版本兼容问题（SDK 的 `tools` / `response_format`
在不同版本里参数名变过）。
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterator

import httpx

PROVIDER = (os.getenv("LLM_PROVIDER") or "ollama").strip().lower()

# ---------- 本地 Ollama ----------
OLLAMA_BASE = os.getenv("AI_API_BASE", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("AI_MODEL", "qwen2.5:7b")
OLLAMA_EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")

# ---------- 阿里云百炼 ----------
BAILIAN_API_KEY = (os.getenv("BAILIAN_API_KEY") or "").strip()
BAILIAN_BASE_URL = os.getenv(
    "BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
).rstrip("/")
BAILIAN_MODEL = os.getenv("BAILIAN_MODEL", "qwen-plus")
BAILIAN_EMBED_MODEL = os.getenv("BAILIAN_EMBED_MODEL", "text-embedding-v3")
BAILIAN_TIMEOUT = float(os.getenv("BAILIAN_TIMEOUT", "120"))
# 百炼的向量接口对单次条数有限制，保守取 10，超了会被拒
BAILIAN_EMBED_BATCH = int(os.getenv("BAILIAN_EMBED_BATCH", "10"))


def chat_model() -> str:
    return BAILIAN_MODEL if PROVIDER == "bailian" else OLLAMA_MODEL


def embed_model() -> str:
    return BAILIAN_EMBED_MODEL if PROVIDER == "bailian" else OLLAMA_EMBED_MODEL


def describe() -> dict:
    """给 /api/ai/info 用：说明当前接的是谁。**不返回 key 本身。**"""
    return {
        "provider": PROVIDER,
        "chat_model": chat_model(),
        "embed_model": embed_model(),
        "api_key_configured": bool(BAILIAN_API_KEY) if PROVIDER == "bailian" else True,
        "base_url": BAILIAN_BASE_URL if PROVIDER == "bailian" else OLLAMA_BASE,
    }


class LLMError(RuntimeError):
    """模型调用失败。带上状态码和响应片段，方便排查是 key 错还是模型名错。"""


class BailianChatClient:
    """百炼（OpenAI 兼容模式）的客户端，形状对齐 `ollama.Client`。"""

    def __init__(self, api_key: str | None = None,
                 base_url: str | None = None,
                 timeout: float | None = None) -> None:
        self.api_key = (api_key if api_key is not None else BAILIAN_API_KEY).strip()
        self.base_url = (base_url or BAILIAN_BASE_URL).rstrip("/")
        self.timeout = timeout or BAILIAN_TIMEOUT
        if not self.api_key:
            raise LLMError(
                "未配置 BAILIAN_API_KEY。请把阿里云百炼的 key 写进 backend/.env，"
                "不要把 key 提交到代码仓库。"
            )

    # ---------------------------------------------------------- 对外接口

    def chat(
        self,
        model: str | None = None,
        messages: list[dict] | None = None,
        stream: bool = False,
        tools: list[dict] | None = None,
        format: str | None = None,
        options: dict | None = None,
        **_: Any,
    ):
        payload: dict[str, Any] = {
            "model": model or chat_model(),
            "messages": messages or [],
            "stream": bool(stream),
        }
        if tools:
            payload["tools"] = tools
        if format == "json":
            # Ollama 用 format="json"，百炼用 response_format
            payload["response_format"] = {"type": "json_object"}
        if options:
            if "temperature" in options:
                payload["temperature"] = options["temperature"]
            if "top_p" in options:
                payload["top_p"] = options["top_p"]
            if "num_predict" in options:
                payload["max_tokens"] = options["num_predict"]

        if stream:
            return self._stream(payload)
        return self._once(payload)

    # ---------------------------------------------------------- 内部

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _raise_for(self, resp: httpx.Response) -> None:
        if resp.status_code == 200:
            return
        snippet = resp.text[:300].replace("\n", " ")
        hint = ""
        if resp.status_code in (401, 403):
            hint = "（key 无效或无权限，检查 BAILIAN_API_KEY）"
        elif resp.status_code == 404:
            hint = "（模型名或 base_url 不对，检查 BAILIAN_MODEL）"
        elif resp.status_code == 429:
            hint = "（触发限流或余额不足）"
        raise LLMError(f"百炼接口返回 {resp.status_code}{hint}：{snippet}")

    def _once(self, payload: dict) -> dict:
        payload = {**payload, "stream": False}
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers, json=payload, timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise LLMError(f"连接百炼失败：{e}") from e
        self._raise_for(resp)

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        return {
            "message": {
                "content": msg.get("content") or "",
                "tool_calls": self._normalize_tool_calls(msg.get("tool_calls")),
            },
            "usage": data.get("usage") or {},
        }

    def _stream(self, payload: dict) -> Iterator[dict]:
        """把 OpenAI 的流式增量拼成 Ollama 形状的整块事件。

        OpenAI 的 tool_calls 是**分片**到达的：
        第一片只有 name，后面的片只有 arguments 的字符串片段。
        而 ReAct 循环期望拿到「一次完整」的 tool_calls，
        所以这里先累积，等流结束后再作为一个 chunk 交出去。
        """
        payload = {**payload, "stream": True}
        pending_tools: dict[int, dict] = {}
        try:
            with httpx.stream(
                "POST", f"{self.base_url}/chat/completions",
                headers=self._headers, json=payload, timeout=self.timeout,
            ) as resp:
                if resp.status_code != 200:
                    resp.read()
                    self._raise_for(resp)

                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except ValueError:
                        continue

                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}

                    content = delta.get("content")
                    if content:
                        yield {"message": {"content": content}}

                    for tc in (delta.get("tool_calls") or []):
                        idx = tc.get("index", 0)
                        slot = pending_tools.setdefault(
                            idx, {"id": tc.get("id"), "name": "", "arguments": ""}
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
        except httpx.HTTPError as e:
            raise LLMError(f"连接百炼失败：{e}") from e

        if pending_tools:
            yield {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": slot["id"],
                            "type": "function",
                            "function": {
                                "name": slot["name"],
                                "arguments": slot["arguments"],
                            },
                        }
                        for _, slot in sorted(pending_tools.items())
                        if slot["name"]
                    ],
                }
            }

    @staticmethod
    def _normalize_tool_calls(raw: Any) -> list[dict]:
        if not isinstance(raw, list):
            return []
        out = []
        for tc in raw:
            fn = (tc or {}).get("function") or {}
            if not fn.get("name"):
                continue
            out.append({
                "id": (tc or {}).get("id"),
                "type": "function",
                "function": {
                    "name": fn.get("name"),
                    "arguments": fn.get("arguments") or "{}",
                },
            })
        return out


def get_chat_client():
    """按配置返回一个「像 ollama.Client 一样」的客户端。"""
    if PROVIDER == "bailian":
        return BailianChatClient()
    import ollama          # 延迟导入：不用 Ollama 的环境不需要这个包
    return ollama.Client(host=OLLAMA_BASE)
