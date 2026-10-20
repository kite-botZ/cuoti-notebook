"""RAG 子系统测试：加载闸门 / 切分 / 检索 / 入库 / 接口。

重点覆盖那些「不看代码根本想不到」的坑：

- 扫描件和 `(cid:)` 乱码**必须**在入库前被拦住；
- 康熙部首（`⾥` U+2F50）要 NFKC 归一化成 `里` U+91CC，否则检索永远命中不了；
- 单页文档要能切出多个片段，且重叠不丢内容；
- BM25 里「查询和语料毫无关系」必须返回空，不能硬塞一条低分噪音进 prompt；
- 不同 embedding 模型的向量不能混算。

所有用例都不依赖 Ollama：向量部分注入 `HashingEmbedder`。
"""

import io
import json
import unicodedata

import pytest
from docx import Document

from app.models import DocumentChunk, KnowledgeDocument
from app.rag.chunker import chunk_pages, is_heading, normalize
from app.rag.embedder import HashingEmbedder, cosine
from app.rag.loader import LoadError, Page, load_document, readability
from app.rag.retriever import BM25, hybrid_search, tokenize
from app.rag.service import ingest_document, retrieve


# ============================================================
# 1. 可读性闸门
# ============================================================

def test_readability_accepts_normal_chinese():
    text = "中心理解题的总原则是先看问题，再用句号划分层次，理清脉络与主体。"
    stat = readability(text * 5)
    assert stat["verdict"] == "ok"
    assert stat["common_ratio"] > 0.5


def test_readability_rejects_cid_garbage():
    text = "公众号资料 (cid:23680)(cid:13978)(cid:30211)(cid:30193)(cid:9339)" * 10
    stat = readability(text)
    assert stat["verdict"] == "garbage"
    assert stat["cid_ratio"] > 0.02


def test_readability_rejects_rare_char_garbage():
    # 实测从某份 PDF 抽出来的真实乱码：全是生僻字，高频字几乎没有
    text = "岀㚚瘃痱⑻ά暑岇Ẍẗ痲㴭㞕⢆䣌䜐㊢㴭Ⓒ恓⢆䣌岊䜐Ⱙ⯜痵⾆尺⇔Ⓒ⢆䣌岊痵" * 6
    stat = readability(text)
    assert stat["verdict"] == "garbage"
    assert stat["common_ratio"] < 0.15


def test_readability_too_short():
    assert readability("短")["verdict"] == "too_short"


# ============================================================
# 2. 加载
# ============================================================

def make_docx(paragraphs) -> bytes:
    d = Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_load_docx_strips_header_footer_noise():
    content = make_docx([
        "公众号：叛逆小樱桃资料 第1/23页",
        "中心理解题的总原则是先看问题，再用句号划分层次。",
        "第 2/23 页",
        "主体一致、话题一致，符合题干要求才能选。",
    ])
    doc = load_document("notes.docx", content)
    assert "公众号" not in doc.text
    assert "中心理解题" in doc.text


def test_load_rejects_unsupported_type():
    with pytest.raises(LoadError, match="不支持"):
        load_document("a.exe", b"xx")


def test_load_rejects_empty():
    with pytest.raises(LoadError, match="空"):
        load_document("a.txt", b"")


def test_load_scanned_pdf_is_rejected():
    """真实扫描件的特征：抽出来 0 字符。这里用一段假 PDF 字节模拟。"""
    with pytest.raises(LoadError):
        load_document("scan.pdf", b"%PDF-1.4\nnot really a pdf")


def test_load_text_normalizes_gbk():
    content = ("这是一段用国标编码保存的中文材料，用来测试解码回退路径是否生效。"
               * 2).encode("gb18030")
    doc = load_document("a.txt", content)
    assert "国标编码" in doc.text


def test_load_text_rejects_garbage():
    """乱码文本必须在加载阶段就被拦住，而不是等到检索时才发现。"""
    garbage = "岀㚚瘃痱⑻ά暑岇Ẍẗ痲㴭㞕⢆䣌䜐㊢㴭Ⓒ恓" * 20
    with pytest.raises(LoadError, match="不像正常中文"):
        load_document("bad.txt", garbage.encode("utf-8"))


# ============================================================
# 3. 归一化与切分
# ============================================================

def test_normalize_fixes_kangxi_radicals():
    """真实材料里 `阿⾥⽊江` 用的是康熙部首字符，NFKC 后必须变成标准汉字。

    这是实测发现的问题：人眼看不出区别，但向量和检索完全对不上。
    U+2FA5 = 康熙部首「里」，U+2F4A = 康熙部首「木」。
    """
    raw = "阿\u2fa5\u2f4a江言语理解"
    assert unicodedata.normalize("NFKC", "\u2fa5") == "里"      # 确认部首定义没记错
    fixed = normalize(raw)
    assert fixed == "阿里木江言语理解"
    assert "里" in fixed and "木" in fixed


def test_normalize_collapses_whitespace():
    assert normalize("a   b\n\n\n\nc") == "a b\n\nc"


@pytest.mark.parametrize("line", [
    "一、中心理解题", "（一）总原则", "1. 先看问题", "第二章 言语理解",
    "【重点】关联词", "中心理解题",
])
def test_is_heading_true(line):
    assert is_heading(line) is True


@pytest.mark.parametrize("line", [
    "这是一个完整的句子，用来测试标题判断。",
    "总原则：先看问题，再用句号划分层次；主体一致、话题一致，符合题干。",
])
def test_is_heading_false(line):
    assert is_heading(line) is False


def test_chunk_single_page_produces_multiple_chunks():
    long_text = "\n".join(
        f"第{i}段：中心理解题的总原则是先看问题，再用句号划分层次，理清脉络层次。" * 3
        for i in range(20)
    )
    chunks = chunk_pages([Page(page_no=1, text=long_text)], target=300)
    assert len(chunks) > 3
    assert all(c.char_count <= 300 * 1.8 + 200 for c in chunks)


def test_chunk_keeps_chapter_path():
    text = "\n".join([
        "一、中心理解题",
        "总原则：先看问题，再用句号划分层次，理清脉络层次与主体一致。" * 6,
        "二、细节判断题",
        "细节题要回到原文逐句比对，注意偷换概念和无中生有。" * 6,
    ])
    chunks = chunk_pages([Page(page_no=1, text=text)], target=200)
    chapters = " ".join(c.chapter for c in chunks)
    assert "中心理解题" in chapters


def test_chunk_overlap_shares_content():
    body = "。".join(f"第{i}句话内容在这里" for i in range(60)) + "。"
    chunks = chunk_pages([Page(page_no=1, text=body)], target=200, overlap=60)
    assert len(chunks) >= 2
    # 前一段的结尾应该出现在后一段的开头附近
    tail = chunks[0].text[-30:]
    assert tail[:10] in chunks[1].text[:200]


def test_chunk_merges_tiny_tail():
    text = "这是一段正常长度的内容，包含足够多的字数用于切分测试。" * 8 + "\n短尾。"
    chunks = chunk_pages([Page(page_no=1, text=text)], target=200, min_chars=80)
    assert all(c.char_count >= 80 or len(chunks) == 1 for c in chunks)


# ============================================================
# 4. 检索
# ============================================================

def test_tokenize_mixes_cjk_bigrams_and_ascii():
    tokens = tokenize("BM25 检索")
    assert "bm25" in tokens
    assert "检索" in tokens


def test_bm25_ranks_relevant_doc_first():
    docs = [
        "言语理解的中心理解题要先看问题再划分层次。",
        "图形推理要观察位置规律和样式规律。",
        "资料分析注意单位换算和增长率计算。",
    ]
    bm = BM25(docs)
    scores = bm.scores("图形推理 位置规律")
    assert scores[1] == max(scores)


def test_bm25_irrelevant_query_gives_zero():
    bm = BM25(["言语理解先看问题", "图形推理看位置规律"])
    assert max(bm.scores("量子力学薛定谔")) == 0.0


def test_hybrid_search_returns_empty_on_no_match():
    hits = hybrid_search("量子纠缠", [{"text": "言语理解先看问题"}])
    assert hits == []


def test_hybrid_search_prefers_bm25_hit_without_vectors():
    cands = [
        {"text": "言语理解的中心理解题先看问题再划分层次。"},
        {"text": "图形推理观察位置规律、样式规律和数量规律。"},
    ]
    hits = hybrid_search("图形推理", cands, top_k=2)
    assert hits[0]["text"].startswith("图形推理")
    assert hits[0]["bm25_score"] > 0
    assert hits[0]["vector_score"] == 0.0     # 没有向量，向量分应为 0


def test_hybrid_search_combines_vector_and_bm25():
    embedder = HashingEmbedder(dim=64)
    cands = [
        {"text": "中心理解题先看问题", "embedding": None},
        {"text": "图形推理看位置规律", "embedding": None},
    ]
    vecs = embedder.embed([c["text"] for c in cands])
    for c, v in zip(cands, vecs):
        c["embedding"] = v
        c["embed_model"] = embedder.model

    qvec = embedder.embed(["图形推理"])[0]
    hits = hybrid_search("图形推理", cands, query_embedding=qvec,
                         embed_model=embedder.model, top_k=2)
    assert hits[0]["text"].startswith("图形推理")
    assert hits[0]["vector_score"] >= 0


def test_hybrid_search_skips_vectors_from_other_model():
    """换了 embedding 模型，旧向量不能参与相似度计算。"""
    embedder = HashingEmbedder(dim=32)
    vec = embedder.embed(["图形推理"])[0]
    cands = [{"text": "图形推理", "embedding": vec, "embed_model": "old-model"}]
    hits = hybrid_search("图形推理", cands, query_embedding=vec,
                         embed_model="new-model", top_k=1)
    assert hits[0]["vector_score"] == 0.0


def test_cosine_basic():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([], [1, 2]) == 0.0
    assert cosine([1, 2], [1, 2, 3]) == 0.0


# ============================================================
# 5. 入库服务
# ============================================================

SAMPLE = """一、中心理解题
总原则：先看问题，再用句号划分层次，理清脉络层次。主体一致、话题一致、符合题干。
首句圈出主语，要讲的话题通常在首句。除了开头举例子，首句一般都很重要。
关联词：转折（后重要）、递进（后重要）、因果（果重要）。

二、细节判断题
细节判断题要回到原文逐句比对，注意偷换概念、无中生有、以偏概全这些常见错法。
选项里出现绝对化表述时尤其要小心，回到原文确认有没有对应的说法。
"""


def test_ingest_document_ready(db):
    content = SAMPLE.encode("utf-8")
    doc = ingest_document(
        db=db, filename="言语.md", content=content,
        title="言语理解笔记", subject="行测",
        embedder=HashingEmbedder(dim=32),
    )
    assert doc.status == "ready", doc.error
    assert doc.chunk_count > 0
    assert doc.embed_model == "hashing-256" or doc.embed_model.startswith("hashing")
    assert db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc.id).count() == doc.chunk_count


def test_ingest_records_failure_reason(db):
    doc = ingest_document(
        db=db, filename="bad.txt", content=("岀㚚瘃痱⑻ά暑岇Ẍẗ痲" * 30).encode(),
        title="乱码", subject="行测", embedder=HashingEmbedder(dim=16),
    )
    assert doc.status == "failed"
    assert doc.failed_stage == "load"
    assert "不像正常中文" in doc.error


def test_ingest_without_embedder_still_ready(db, monkeypatch):
    """向量服务不可用时要降级为 BM25，而不是入库失败。"""
    monkeypatch.setattr("app.rag.service.get_embedder", lambda *a, **k: None)
    doc = ingest_document(
        db=db, filename="言语.md", content=SAMPLE.encode(),
        title="言语理解笔记", subject="行测",
    )
    assert doc.status == "ready"
    assert doc.embed_model == ""
    rows = db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc.id).all()
    assert all(c.embedding is None for c in rows)


# ============================================================
# 6. 检索服务
# ============================================================

def _ingest_sample(db, subject="行测"):
    return ingest_document(
        db=db, filename="言语.md", content=SAMPLE.encode(),
        title="言语理解笔记", subject=subject,
        embedder=HashingEmbedder(dim=32),
    )


def test_retrieve_hits_relevant_chunk(db):
    doc = _ingest_sample(db)
    assert doc.status == "ready"
    result = retrieve(db=db, query="细节判断题怎么比对原文",
                      embedder=HashingEmbedder(dim=32))
    assert result["candidates"] > 0
    assert result["hits"]
    assert "细节" in result["hits"][0]["text"]


def test_retrieve_empty_query(db):
    _ingest_sample(db)
    assert retrieve(db=db, query="   ")["hits"] == []


def test_retrieve_no_docs(db):
    result = retrieve(db=db, query="随便问问")
    assert result["hits"] == []
    assert "message" in result


def test_retrieve_respects_subject_filter(db):
    _ingest_sample(db, subject="行测")
    assert retrieve(db=db, query="细节判断题", subject="申论")["hits"] == []
    assert retrieve(db=db, query="细节判断题", subject="行测")["hits"]


def test_retrieve_reports_mode(db):
    _ingest_sample(db)
    result = retrieve(db=db, query="中心理解题",
                      embedder=HashingEmbedder(dim=32))
    assert result["mode"] in ("hybrid", "bm25", "vector")


# ============================================================
# 7. HTTP 接口
# ============================================================

def test_upload_document_endpoint(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.rag.service.get_embedder", lambda *a, **k: None)
    resp = client.post(
        "/api/knowledge-docs",
        files={"file": ("言语.md", SAMPLE.encode(), "text/markdown")},
        data={"title": "言语理解笔记", "subject": "行测"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["chunk_count"] > 0
    assert "入库成功" in body["message"]


def test_upload_rejects_unsupported(client, auth_headers):
    resp = client.post(
        "/api/knowledge-docs",
        files={"file": ("a.exe", b"xx", "application/octet-stream")},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_upload_requires_login(client):
    resp = client.post(
        "/api/knowledge-docs",
        files={"file": ("a.md", SAMPLE.encode(), "text/markdown")},
    )
    assert resp.status_code == 401


def test_list_and_delete_document(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.rag.service.get_embedder", lambda *a, **k: None)
    doc = client.post(
        "/api/knowledge-docs",
        files={"file": ("a.md", SAMPLE.encode(), "text/markdown")},
        data={"subject": "行测"}, headers=auth_headers,
    ).json()

    listed = client.get("/api/knowledge-docs").json()
    assert any(d["id"] == doc["id"] for d in listed)

    assert client.delete(f"/api/knowledge-docs/{doc['id']}",
                         headers=auth_headers).status_code == 200
    assert client.get("/api/knowledge-docs").json() == []


def test_chunks_endpoint(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.rag.service.get_embedder", lambda *a, **k: None)
    doc = client.post(
        "/api/knowledge-docs",
        files={"file": ("a.md", SAMPLE.encode(), "text/markdown")},
        data={"subject": "行测"}, headers=auth_headers,
    ).json()

    resp = client.get(f"/api/knowledge-docs/{doc['id']}/chunks?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["chunks"]) <= 2
    assert body["chunks"][0]["text"]


def test_rag_search_endpoint(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.rag.service.get_embedder", lambda *a, **k: None)
    client.post(
        "/api/knowledge-docs",
        files={"file": ("a.md", SAMPLE.encode(), "text/markdown")},
        data={"subject": "行测"}, headers=auth_headers,
    )
    resp = client.post("/api/rag/search",
                       json={"query": "细节判断 偷换概念", "top_k": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert body["hits"]
    assert "bm25_score" in body["hits"][0]
    assert "vector_score" in body["hits"][0]


def test_rag_stats_endpoint(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.rag.service.get_embedder", lambda *a, **k: None)
    client.post(
        "/api/knowledge-docs",
        files={"file": ("a.md", SAMPLE.encode(), "text/markdown")},
        data={"subject": "行测"}, headers=auth_headers,
    )
    stats = client.get("/api/rag/stats").json()
    assert stats["documents"] == 1
    assert stats["chunks"] > 0
    assert stats["embedding_coverage"] == 0.0     # 本次没有向量，降级为 BM25
