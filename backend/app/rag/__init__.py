"""RAG（检索增强生成）子系统。

| 模块 | 职责 |
|---|---|
| `loader` | 从 PDF / DOCX / Markdown / TXT 抽出文本，并做**可读性闸门**（挡住扫描件和乱码） |
| `chunker` | NFKC 归一化（修康熙部首）、按章节维护标题路径、带重叠切分 |
| `embedder` | 向量化：本地 Ollama（默认 `bge-m3`），另有测试用的哈希向量器 |
| `retriever` | BM25 关键词 + 向量语义的**混合检索**，各自归一化后加权 |
| `service` | 入库（加载→切分→向量化→落库）与检索的编排 |

设计上的两个重要取舍：

1. **不引入向量数据库**。几千个 chunk 直接在 MySQL 里存 JSON、
   查到内存里算余弦就够用了，省掉一整套依赖。上量后换 pgvector / Chroma
   只需替换 `retriever`，`service` 和路由不用动。
2. **向量服务不可用也能跑**。`get_embedder()` 拿不到模型就返回 None，
   检索自动退化成纯 BM25，入库照常进行（只是不存向量）。
"""

from app.rag.chunker import Chunk, chunk_pages, normalize
from app.rag.embedder import HashingEmbedder, OllamaEmbedder, cosine, get_embedder
from app.rag.loader import LoadError, LoadedDoc, load_document, readability
from app.rag.retriever import BM25, hybrid_search, tokenize
from app.rag.service import IngestError, ingest_document, retrieve

__all__ = [
    "Chunk", "chunk_pages", "normalize",
    "HashingEmbedder", "OllamaEmbedder", "cosine", "get_embedder",
    "LoadError", "LoadedDoc", "load_document", "readability",
    "BM25", "hybrid_search", "tokenize",
    "IngestError", "ingest_document", "retrieve",
]
