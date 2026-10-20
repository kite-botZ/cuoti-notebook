"""知识库文档管理 + 检索调试接口。

| 方法 | 路径 | 作用 |
|---|---|---|
| POST   | `/api/knowledge-docs` | 上传教材/讲义，入库（解析→切分→向量化） |
| GET    | `/api/knowledge-docs` | 列出知识库文档及处理状态 |
| DELETE | `/api/knowledge-docs/{id}` | 删除文档（级联删掉它的片段） |
| GET    | `/api/knowledge-docs/{id}/chunks` | 查看切分结果（调参用） |
| POST   | `/api/rag/search` | **检索调试**：看给定 query 能召回哪些片段、分数怎么来的 |
| GET    | `/api/rag/stats` | 知识库统计：文档数、片段数、向量覆盖率 |

`/api/rag/search` 是这一步的核心验收工具：把 `bm25_score` / `vector_score` / `score`
都返回出来，能直接看出混合检索是不是真的比单路好——这也就是论文里那张对比表的来源。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import DocumentChunk, KnowledgeDocument
from app.rag.service import (
    DEFAULT_ALPHA,
    DEFAULT_MIN_COVERAGE,
    DEFAULT_TOP_K,
    ingest_document,
    retrieve,
)
from app.routes.ai import AI_API_BASE
from app.routes.banks import current_user_id

router = APIRouter(prefix="/api", tags=["rag"])

# 上传大小上限。注意要和 Nginx 的 client_max_body_size 对齐，
# 否则请求会在 Nginx 层被 413 掉，后端根本没机会拒绝。
MAX_DOC_SIZE = int(os.getenv("RAG_MAX_DOC_SIZE", str(30 * 1024 * 1024)))
SUPPORTED = (".pdf", ".docx", ".md", ".markdown", ".txt")


class SearchBody(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=20)
    subject: str | None = None
    kp_ids: list[int] | None = None
    doc_ids: list[int] | None = None
    alpha: float = Field(default=DEFAULT_ALPHA, ge=0.0, le=1.0)
    min_coverage: float = Field(default=DEFAULT_MIN_COVERAGE, ge=0.0, le=1.0)


def _doc_payload(doc: KnowledgeDocument) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "subject": doc.subject,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "char_count": doc.char_count,
        "chunk_count": doc.chunk_count,
        "status": doc.status,
        "failed_stage": doc.failed_stage,
        "error": doc.error,
        "embed_model": doc.embed_model,
        "created_at": str(doc.created_at) if doc.created_at else None,
    }


# ============================================================
# 文档入库
# ============================================================

@router.post("/knowledge-docs", status_code=201)
def upload_document(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    subject: str = Form(default="综合"),
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """上传并入库一份文档。

    接口是同步 `def`：入库里有 embedding 调用（可能几十秒），
    FastAPI 会把它丢进线程池，不会卡住事件循环。
    """
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED:
        raise HTTPException(
            status_code=422,
            detail=f"不支持 {ext or '(无扩展名)'}，目前支持 {'/'.join(SUPPORTED)}",
        )

    content = file.file.read()
    if not content:
        raise HTTPException(status_code=422, detail="文件是空的")
    if len(content) > MAX_DOC_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {MAX_DOC_SIZE // 1024 // 1024}MB",
        )

    doc = ingest_document(
        db=db,
        filename=filename,
        content=content,
        title=title or os.path.splitext(filename)[0],
        subject=subject,
        uploaded_by=user_id,
        ai_api_base=AI_API_BASE,
    )

    payload = _doc_payload(doc)
    if doc.status == "failed":
        # 入库失败也要把原因原样告诉用户（扫描件 / 乱码 / 切分失败）
        payload["message"] = f"入库失败（{doc.failed_stage}）：{doc.error}"
        return payload
    payload["message"] = (
        f"入库成功：切出 {doc.chunk_count} 个片段"
        + ("，已建向量索引" if doc.embed_model else "，仅建 BM25 索引")
    )
    return payload


@router.get("/knowledge-docs")
def list_documents(
    subject: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(KnowledgeDocument)
    if subject:
        query = query.filter(KnowledgeDocument.subject == subject)
    rows = query.order_by(KnowledgeDocument.id.desc()).all()
    return [_doc_payload(d) for d in rows]


@router.delete("/knowledge-docs/{doc_id}")
def delete_document(
    doc_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    db.delete(doc)          # chunk 由外键 CASCADE 一起删
    db.commit()
    return {"message": "已删除", "id": doc_id}


@router.get("/knowledge-docs/{doc_id}/chunks")
def list_chunks(
    doc_id: int,
    limit: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.doc_id == doc_id)
        .order_by(DocumentChunk.chunk_index)
        .limit(limit)
        .all()
    )
    return {
        "doc_id": doc_id,
        "title": doc.title,
        "chunk_count": doc.chunk_count,
        "chunks": [
            {
                "index": c.chunk_index,
                "chapter": c.chapter,
                "page": c.page,
                "char_count": c.char_count,
                "has_embedding": bool(c.embedding),
                "text": c.text[:400],
            }
            for c in rows
        ],
    }


# ============================================================
# 检索
# ============================================================

@router.post("/rag/search")
def rag_search(body: SearchBody, db: Session = Depends(get_db)):
    """检索知识库。返回分数明细，方便判断参数是否合理。"""
    result = retrieve(
        db=db,
        query=body.query,
        top_k=body.top_k,
        subject=body.subject,
        kp_ids=body.kp_ids,
        doc_ids=body.doc_ids,
        alpha=body.alpha,
        min_coverage=body.min_coverage,
        ai_api_base=AI_API_BASE,
    )
    # 正文只回前 500 字，避免调试接口的响应过大
    for hit in result["hits"]:
        hit["text"] = hit["text"][:500]
    return result


@router.get("/rag/stats")
def rag_stats(db: Session = Depends(get_db)):
    docs = db.query(KnowledgeDocument).all()
    chunks = db.query(DocumentChunk).count()
    with_vec = db.query(DocumentChunk).filter(DocumentChunk.embedding.isnot(None)).count()
    with_kp = db.query(DocumentChunk).filter(DocumentChunk.kp_id.isnot(None)).count()

    return {
        "documents": len(docs),
        "documents_ready": sum(1 for d in docs if d.status == "ready"),
        "documents_failed": sum(1 for d in docs if d.status == "failed"),
        "chunks": chunks,
        "chunks_with_embedding": with_vec,
        "embedding_coverage": round(with_vec / chunks, 4) if chunks else 0.0,
        "chunks_with_kp": with_kp,
        "kp_coverage": round(with_kp / chunks, 4) if chunks else 0.0,
        "subjects": sorted({d.subject for d in docs}),
    }
