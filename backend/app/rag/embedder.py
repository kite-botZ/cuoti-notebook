"""文本向量化。

支持两种来源，由 `LLM_PROVIDER` 决定：

- `ollama`（默认）：本地 `bge-m3`，不花钱、数据不出机器，但要先 `ollama pull`；
- `bailian`：阿里云百炼的 `text-embedding-v3`，不用本地算力，适合部署在
  小规格云服务器上（本地跑 embedding 很吃内存）。

**拿不到模型就自动降级**——检索层退化成纯 BM25 关键词检索，功能照样能用，
只是语义召回弱一些。这是刻意的设计：向量服务不该成为整条链路的单点。

换模型时要注意：不同模型的向量不能混算相似度，所以每个 chunk 都存了
`embed_model`，检索时只对同一模型的向量做距离计算。
"""

from __future__ import annotations

import hashlib
import math
import os
import time
from typing import Protocol

import httpx

from app.llm import (
    BAILIAN_API_KEY,
    BAILIAN_BASE_URL,
    BAILIAN_EMBED_BATCH,
    BAILIAN_EMBED_MODEL,
    BAILIAN_TIMEOUT,
    OLLAMA_BASE,
    PROVIDER,
    embed_model,
)

DEFAULT_EMBED_MODEL = embed_model()
EMBED_TIMEOUT = float(os.getenv("EMBED_TIMEOUT", "120"))


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    """调用 Ollama 的 `/api/embed` 接口。

    直接用 httpx 而不是 ollama 客户端：不同版本的客户端方法名变过
    （`embeddings` / `embed`），HTTP 接口是稳定的。
    """

    def __init__(self, base_url: str, model: str = DEFAULT_EMBED_MODEL) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = httpx.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": texts},
            timeout=EMBED_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        vectors = data.get("embeddings")
        if not vectors or len(vectors) != len(texts):
            raise RuntimeError(
                f"embedding 返回异常：期望 {len(texts)} 条，拿到 {len(vectors or [])} 条"
            )
        return vectors

    def available(self, timeout: float = 3.0) -> bool:
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=timeout)
            resp.raise_for_status()
            names = [m.get("name", "") for m in resp.json().get("models", [])]
        except Exception:  # noqa: BLE001
            return False
        # 模型名可能带 tag（bge-m3:latest）
        return any(n == self.model or n.startswith(f"{self.model}:") for n in names)


class HashingEmbedder:
    """确定性哈希向量器，**只给单测用**。

    它没有任何语义能力（「苹果」和「水果」不会是近邻），
    但能让"切分 → 向量 → 存储 → 检索"这条管道的测试不依赖网络和模型。
    """

    def __init__(self, dim: int = 256, model: str = "hashing-256") -> None:
        self.dim = dim
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for token in _char_bigrams(text):
                h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
                vec[h % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class BailianEmbedder:
    """阿里云百炼的文本向量（`text-embedding-v3`，OpenAI 兼容接口）。

    百炼对单次请求的条数有限制（超过会直接报错），所以要分批。
    分批发还有一个好处：大批量入库时不会因为一次请求体过大而整体失败。
    """

    def __init__(self, api_key: str | None = None,
                 base_url: str | None = None,
                 model: str | None = None,
                 batch_size: int | None = None) -> None:
        self.api_key = (api_key if api_key is not None else BAILIAN_API_KEY).strip()
        self.base_url = (base_url or BAILIAN_BASE_URL).rstrip("/")
        self.model = model or BAILIAN_EMBED_MODEL
        self.batch_size = max(1, batch_size or BAILIAN_EMBED_BATCH)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.api_key:
            raise RuntimeError("未配置 BAILIAN_API_KEY，无法调用百炼向量接口")

        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            resp = httpx.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "input": batch, "encoding_format": "float"},
                timeout=BAILIAN_TIMEOUT,
            )
            if resp.status_code != 200:
                snippet = resp.text[:300].replace("\n", " ")
                hint = "（key 无效或无权限）" if resp.status_code in (401, 403) else ""
                raise RuntimeError(
                    f"百炼向量接口返回 {resp.status_code}{hint}：{snippet}"
                )
            data = resp.json().get("data") or []
            # 接口返回的顺序理论上与输入一致，仍按 index 排一次，避免顺序错乱
            data = sorted(data, key=lambda d: d.get("index", 0))
            if len(data) != len(batch):
                raise RuntimeError(
                    f"百炼向量返回条数不符：期望 {len(batch)}，拿到 {len(data)}"
                )
            out.extend([d.get("embedding") or [] for d in data])
        return out

    def available(self, timeout: float = 5.0) -> bool:
        """有 key 就认为可用——真正的可用性由第一次 embed 调用来暴露。

        不在这里主动发请求探测：向量接口按 token 计费，每次请求都探一下
        等于白花钱。
        """
        return bool(self.api_key)


def _char_bigrams(text: str) -> list[str]:
    s = "".join(ch for ch in text if ch.strip())
    if len(s) < 2:
        return [s] if s else []
    return [s[i:i + 2] for i in range(len(s) - 1)]


# 缓存「模型是否可用」的探测结果，避免每个请求都去 ping 一次
_AVAIL_CACHE: dict[str, tuple[bool, float]] = {}
_AVAIL_TTL = 30.0


def get_embedder(base_url: str | None = None,
                 model: str | None = None):
    """拿到一个可用的向量器；不可用返回 None（调用方走 BM25 降级）。"""
    if PROVIDER == "bailian":
        if not BAILIAN_API_KEY:
            return None
        return BailianEmbedder()

    base_url = base_url or OLLAMA_BASE
    model = model or DEFAULT_EMBED_MODEL
    key = f"{base_url}|{model}"
    now = time.time()
    cached = _AVAIL_CACHE.get(key)
    if cached and now - cached[1] < _AVAIL_TTL:
        return OllamaEmbedder(base_url, model) if cached[0] else None

    embedder = OllamaEmbedder(base_url, model)
    ok = embedder.available()
    _AVAIL_CACHE[key] = (ok, now)
    return embedder if ok else None


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（入参已归一化时可直接点乘，这里仍做一次保护）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
