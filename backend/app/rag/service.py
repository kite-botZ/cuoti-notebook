"""RAG 服务层：把「加载 → 切分 → 向量化 → 落库」和「检索」串起来。

放 service 层而不是塞进路由，是因为这两件事都要被别处复用：
- 入库：以后可能由命令行脚本批量灌教材，不经过 HTTP；
- 检索：下一步要接进 `/api/ai/explain`，那是另一个路由模块。
"""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.models import DocumentChunk, KnowledgeDocument
from app.rag.chunker import chunk_pages
from app.rag.embedder import DEFAULT_EMBED_MODEL, get_embedder
from app.rag.loader import LoadError, load_document
from app.rag.retriever import hybrid_search, mode_of

EMBED_BATCH = int(os.getenv("EMBED_BATCH", "32"))
DEFAULT_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
DEFAULT_ALPHA = float(os.getenv("RAG_ALPHA", "0.5"))
# 查询词命中率下限：低于这个值说明片段基本不相关，宁可返回空也别塞噪音
DEFAULT_MIN_COVERAGE = float(os.getenv("RAG_MIN_COVERAGE", "0.2"))


class IngestError(Exception):
    pass


def ingest_document(
    db: Session,
    filename: str,
    content: bytes,
    title: str,
    subject: str,
    uploaded_by: int | None = None,
    ai_api_base: str = "http://localhost:11434",
    embed_model: str = DEFAULT_EMBED_MODEL,
    embedder=None,
) -> KnowledgeDocument:
    """把一份文档灌进知识库。

    失败时不是抛异常就完事——会把失败原因写进 `KnowledgeDocument`
    （status=failed + failed_stage + error），前端能显示「哪一步错了」，
    而不是只看到一句 "500"。
    """
    doc = KnowledgeDocument(
        title=(title or filename or "未命名文档")[:200],
        subject=(subject or "综合")[:50],
        filename=filename or "",
        uploaded_by=uploaded_by,
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    def fail(stage: str, msg: str) -> KnowledgeDocument:
        doc.status = "failed"
        doc.failed_stage = stage
        doc.error = msg[:1000]
        db.commit()
        return doc

    # ---------- 1. 加载 + 可读性闸门 ----------
    try:
        loaded = load_document(filename, content)
    except LoadError as e:
        return fail("load", str(e))
    except Exception as e:  # noqa: BLE001
        return fail("load", f"解析失败：{e}")

    doc.file_type = loaded.file_type
    doc.char_count = loaded.char_count

    # ---------- 2. 切分 ----------
    try:
        chunks = chunk_pages(loaded.pages)
    except Exception as e:  # noqa: BLE001
        return fail("chunk", f"切分失败：{e}")

    if not chunks:
        return fail("chunk", "切分后没有任何片段，文档可能太短或格式异常")

    # ---------- 3. 向量化（失败不阻断入库）----------
    # embedder 可以由调用方注入（单测里塞哈希向量器，就不依赖 Ollama 了）
    vectors: list[list[float] | None] = [None] * len(chunks)
    used_model = ""
    if embedder is None:
        try:
            embedder = get_embedder(ai_api_base, embed_model)
        except Exception:  # noqa: BLE001
            embedder = None

    if embedder:
        try:
            for i in range(0, len(chunks), EMBED_BATCH):
                batch = chunks[i:i + EMBED_BATCH]
                vecs = embedder.embed([c.text for c in batch])
                for j, v in enumerate(vecs):
                    vectors[i + j] = v
            used_model = embedder.model
        except Exception as e:  # noqa: BLE001
            # 降级：没有向量也能用 BM25 检索，比整个入库失败强
            loaded.warnings.append(f"向量化失败，已降级为关键词检索：{e}")
            vectors = [None] * len(chunks)
            used_model = ""
    else:
        loaded.warnings.append(
            f"未找到 embedding 模型 {embed_model}，本次只建 BM25 索引"
            f"（执行 `ollama pull {embed_model}` 后重建即可启用语义检索）"
        )

    # ---------- 4. 落库 ----------
    try:
        for chunk, vec in zip(chunks, vectors):
            db.add(DocumentChunk(
                doc_id=doc.id,
                chunk_index=chunk.index,
                text=chunk.text,
                char_count=chunk.char_count,
                subject=doc.subject,
                chapter=chunk.chapter,
                page=chunk.page,
                embedding=vec,
                embed_model=used_model if vec else "",
            ))
        doc.chunk_count = len(chunks)
        doc.embed_model = used_model
        doc.status = "ready"
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return fail("store", f"写库失败：{e}")

    db.refresh(doc)
    return doc


def _candidates(db: Session, subject: str | None, kp_ids: list[int] | None,
                doc_ids: list[int] | None) -> list[DocumentChunk]:
    query = db.query(DocumentChunk)
    if subject:
        query = query.filter(DocumentChunk.subject == subject)
    if kp_ids:
        query = query.filter(DocumentChunk.kp_id.in_(kp_ids))
    if doc_ids:
        query = query.filter(DocumentChunk.doc_id.in_(doc_ids))
    return query.all()


def retrieve(
    db: Session,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    subject: str | None = None,
    kp_ids: list[int] | None = None,
    doc_ids: list[int] | None = None,
    alpha: float = DEFAULT_ALPHA,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    ai_api_base: str = "http://localhost:11434",
    embed_model: str = DEFAULT_EMBED_MODEL,
    embedder=None,
) -> dict:
    """检索相关片段，返回结构化结果（含检索模式与分数明细，方便调参与写论文）。"""
    if not query or not query.strip():
        return {"query": query, "mode": "none", "hits": [], "candidates": 0}

    rows = _candidates(db, subject, kp_ids, doc_ids)
    if not rows:
        return {
            "query": query, "mode": "none", "hits": [], "candidates": 0,
            "message": "知识库里没有匹配的片段（可能还没导入文档，或过滤条件太严）",
        }

    if embedder is None:
        try:
            embedder = get_embedder(ai_api_base, embed_model)
        except Exception:  # noqa: BLE001
            embedder = None

    query_vec = None
    used_model = ""
    if embedder:
        try:
            query_vec = embedder.embed([query])[0]
            used_model = embedder.model
        except Exception:  # noqa: BLE001
            query_vec = None

    payload = [
        {
            "chunk_id": c.id,
            "doc_id": c.doc_id,
            "text": c.text,
            "chapter": c.chapter,
            "page": c.page,
            "subject": c.subject,
            "kp_id": c.kp_id,
            "embedding": c.embedding,
            "embed_model": c.embed_model,
        }
        for c in rows
    ]

    hits = hybrid_search(
        query=query, candidates=payload, query_embedding=query_vec,
        top_k=top_k, alpha=alpha, embed_model=used_model,
        min_coverage=min_coverage,
    )

    return {
        "query": query,
        "mode": mode_of(alpha, used_vector=bool(query_vec)),
        "embed_model": used_model,
        "candidates": len(rows),
        "hits": hits,
    }
