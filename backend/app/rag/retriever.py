"""检索层：BM25 关键词检索 + 向量语义检索，混合排序。

## 为什么要做混合，而不是只用向量

两边的短板是互补的：

- **纯向量**：能召回"意思相近但用词不同"的段落，但对专有名词、数字、
  教材里的小标题不敏感——用户搜「中心理解题」，向量可能给它一段讲"主旨概括"的文字。
- **纯 BM25**：对术语精确命中很强，但完全不理解同义词。

混合后按权重相加（默认各 0.5），并且**两边各自先做 min-max 归一化**，
否则两个分数量纲不同，加权没有意义——这是实现混合检索最容易写错的地方。

## 元数据过滤为什么放在打分之前

按 `kp_id` / `subject` 过滤能直接把候选集砍掉一两个数量级，
既快又准。但要注意：过滤太狠会漏召回，所以过滤是**可选**的，
调用方不传知识点就退化成全库检索。
"""

from __future__ import annotations

import math
import re
from collections import Counter

from app.rag.embedder import cosine

_CJK = re.compile(r"[\u4e00-\u9fff]")
_ASCII_WORD = re.compile(r"[a-zA-Z0-9]+")


def tokenize(text: str) -> list[str]:
    """中文按 2-gram 切，英文/数字按词切。

    不用 jieba：2-gram 对短查询和术语（「中心理解题」）其实更稳，
    而且不用额外依赖和词典。
    """
    if not text:
        return []
    tokens: list[str] = [w.lower() for w in _ASCII_WORD.findall(text)]
    cjk = "".join(ch for ch in text if _CJK.match(ch))
    if len(cjk) == 1:
        tokens.append(cjk)
    else:
        tokens.extend(cjk[i:i + 2] for i in range(len(cjk) - 1))
    return tokens


class BM25:
    """标准 BM25（k1=1.5, b=0.75）。语料小，直接全量算。"""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_tokens = [Counter(tokenize(d)) for d in docs]
        self.doc_len = [sum(c.values()) for c in self.doc_tokens]
        self.n = len(docs)
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0

        df: Counter = Counter()
        for counter in self.doc_tokens:
            df.update(counter.keys())
        self.idf = {
            term: math.log(1 + (self.n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def scores(self, query: str) -> list[float]:
        q_terms = tokenize(query)
        if not q_terms or not self.n:
            return [0.0] * self.n

        out: list[float] = []
        for i in range(self.n):
            counter = self.doc_tokens[i]
            dl = self.doc_len[i] or 1
            s = 0.0
            for term in q_terms:
                tf = counter.get(term, 0)
                if not tf:
                    continue
                idf = self.idf.get(term, 0.0)
                denom = tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                s += idf * tf * (self.k1 + 1) / denom
            out.append(s)
        return out


def _minmax(values: list[float]) -> list[float]:
    """把一组分数缩放到 [0, 1]。

    **只有一个候选（或所有分数相同）时不能返回全 0**——那会导致
    "唯一一个完美匹配的片段得 0 分，然后被当成噪音过滤掉"。
    这是混合检索里很隐蔽的坑：语料少的时候特别容易踩到。
    所以退化情况按「有分就给满分、全零还是零」处理。
    """
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [1.0 if v > 0 else 0.0 for v in values]
    return [(v - lo) / (hi - lo) for v in values]


def hybrid_search(
    query: str,
    candidates: list[dict],
    query_embedding: list[float] | None = None,
    top_k: int = 5,
    alpha: float = 0.5,
    embed_model: str = "",
    min_coverage: float = 0.0,
) -> list[dict]:
    """对候选片段做混合检索。

    参数
    ----
    candidates : 每项至少含 `text`，可选 `embedding` / `embed_model` / 其它元数据。
    query_embedding : 查询的向量；为 None 则退化成纯 BM25。
    alpha : 向量分权重。1.0=纯向量，0.0=纯 BM25。
    embed_model : 只对**同一模型**生成的向量算相似度，避免不同模型的向量混算。
    min_coverage : 查询词命中率下限。

        **为什么必须有这个参数**：min-max 归一化会把最高分强行拉成 1.0，
        于是「几乎不相关的片段」和「完美命中的片段」在归一化后长得一模一样
        （实测：查询「图形推理的对称性规律」时，仅因为命中「规律」两个字的
        言语理解片段，归一化后也是 1.0 满分）。绝对分数被归一化抹掉了，
        所以要在归一化**之前**用词命中率做一道绝对门槛：
        查询里至少要有 `min_coverage` 比例的 2-gram 在片段里出现过。

    `candidates` 里没有可用向量的片段，其 vector_score 记 0，
    但 BM25 分照常参与——不会因为缺向量就整段丢失。
    """
    if not query or not candidates:
        return []

    texts = [c.get("text", "") for c in candidates]
    bm25 = BM25(texts)
    bm25_raw = bm25.scores(query)
    bm25_norm = _minmax(bm25_raw)

    # 词命中率：查询的 2-gram 有多少比例出现在这个片段里
    q_tokens = set(tokenize(query))
    coverages: list[float] = []
    for text in texts:
        if not q_tokens:
            coverages.append(0.0)
            continue
        d_tokens = set(tokenize(text))
        coverages.append(len(q_tokens & d_tokens) / len(q_tokens))

    vector_norm = [0.0] * len(candidates)
    used_vector = False

    if query_embedding:
        sims: list[float] = []
        usable: list[bool] = []
        for c in candidates:
            emb = c.get("embedding")
            if not emb:
                sims.append(0.0)
                usable.append(False)
                continue
            if embed_model and c.get("embed_model") and c["embed_model"] != embed_model:
                # 换了 embedding 模型，旧向量不可比
                sims.append(0.0)
                usable.append(False)
                continue
            if len(emb) != len(query_embedding):
                sims.append(0.0)
                usable.append(False)
                continue
            sims.append(cosine(query_embedding, emb))
            usable.append(True)

        if any(usable):
            used_vector = True
            sims_norm = _minmax(sims)
            vector_norm = [
                v if ok else 0.0 for v, ok in zip(sims_norm, usable)
            ]

    w_vec = alpha if used_vector else 0.0
    w_bm25 = 1.0 - w_vec

    scored: list[dict] = []
    for i, cand in enumerate(candidates):
        total = w_vec * vector_norm[i] + w_bm25 * bm25_norm[i]
        scored.append({
            **cand,
            "score": round(total, 4),
            "bm25_score": round(bm25_raw[i], 3),
            "vector_score": round(vector_norm[i], 4),
            "coverage": round(coverages[i], 4),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    # 两道过滤：
    # 1) 归一化后为 0 分的（在这一批里垫底）不要；
    # 2) 词命中率不够的（几乎不相关）不要——防止把噪音塞进 prompt。
    top = [
        s for s in scored[:top_k]
        if s["score"] > 0 and s["coverage"] >= min_coverage
    ]
    return top


def mode_of(alpha: float, used_vector: bool) -> str:
    """给调用方/日志用的检索模式标签。"""
    if not used_vector:
        return "bm25"
    if alpha >= 1.0:
        return "vector"
    return "hybrid"
