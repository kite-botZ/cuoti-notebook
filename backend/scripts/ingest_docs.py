"""批量把教材 / 讲义灌进 RAG 知识库（命令行，不需要启动服务）。

用法：

    # 灌一个文件夹里的所有文档
    python scripts/ingest_docs.py "C:\\path\\教材讲义" --subject 行测

    # 同名文档已经入库过的跳过；要覆盖重建就加 --force
    python scripts/ingest_docs.py "C:\\path\\教材讲义" --subject 行测 --force

设计说明：

- **逐文件独立处理**：一份坏文档（扫描件、乱码）不影响其它文档入库，
  失败原因会打印在结果表里。
- **同名文档默认跳过**：重复灌会浪费 embedding 调用（很贵），
  要重建请显式 `--force`。
- 向量模型没装时自动降级为 BM25，只在最后提示一句，不中断流程。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="批量导入知识库文档")
    p.add_argument("path", help="文件或文件夹路径")
    p.add_argument("--subject", default="综合", help="学科标签，用于检索时过滤")
    p.add_argument("--force", action="store_true", help="同名文档已存在时也重新入库")
    p.add_argument("--limit", type=int, default=0, help="最多处理几个文件（0=不限）")
    return p.parse_args()


def collect_files(path_str: str) -> list[Path]:
    path = Path(path_str)
    if path.is_file():
        return [path]
    if not path.is_dir():
        print(f"路径不存在：{path_str}")
        sys.exit(1)
    exts = {".pdf", ".docx", ".md", ".markdown", ".txt"}
    return sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in exts)


def main() -> int:
    args = parse_args()

    # 必须先设 APP_ENV，再 import app.*（app.db 在导入时读环境变量）
    os.environ.setdefault("APP_ENV", "production")
    sys.path.insert(0, str(BACKEND_DIR))

    from app.db import Base, SessionLocal, engine
    from app import models  # noqa: F401  —— 必须导入，否则 create_all 看不到表定义
    from app.models import KnowledgeDocument
    from app.rag.service import ingest_document

    # 命令行灌库不经过 app.main，所以这里要自己建表。
    # 少了这一步，在一个全新的空库上会直接报「表不存在」——报错信息还很难懂。
    Base.metadata.create_all(bind=engine)

    files = collect_files(args.path)
    if not files:
        print("没有找到支持的文件（.pdf / .docx / .md / .txt）")
        return 1

    if args.limit:
        files = files[:args.limit]

    print(f"待处理 {len(files)} 个文件，学科标签：{args.subject}\n")

    db = SessionLocal()
    ok = skipped = failed = 0
    results: list[tuple[str, str, str]] = []

    try:
        for path in files:
            existing = (
                db.query(KnowledgeDocument)
                .filter(KnowledgeDocument.filename == path.name,
                        KnowledgeDocument.subject == args.subject)
                .first()
            )
            if existing and not args.force:
                skipped += 1
                results.append((path.name, "跳过", f"已存在（id={existing.id}）"))
                print(f"  跳过 {path.name}（已存在，用 --force 重建）")
                continue

            if existing and args.force:
                db.delete(existing)
                db.commit()

            size_mb = path.stat().st_size / 1024 / 1024
            print(f"  处理 {path.name}  ({size_mb:.1f} MB) ...", end="", flush=True)

            try:
                content = path.read_bytes()
            except Exception as e:  # noqa: BLE001
                failed += 1
                results.append((path.name, "读文件失败", str(e)[:80]))
                print(" 读取失败")
                continue

            doc = ingest_document(
                db=db,
                filename=path.name,
                content=content,
                title=path.stem,
                subject=args.subject,
            )

            if doc.status == "ready":
                ok += 1
                mode = "含向量" if doc.embed_model else "仅BM25"
                results.append((path.name, "成功",
                                f"{doc.chunk_count} 片段 / {doc.char_count} 字 / {mode}"))
                print(f" 成功：{doc.chunk_count} 个片段")
            else:
                failed += 1
                results.append((path.name, "失败",
                                f"[{doc.failed_stage}] {doc.error[:100]}"))
                print(f"\n     失败（{doc.failed_stage}）：{doc.error[:160]}")
    finally:
        db.close()

    print("\n" + "=" * 76)
    print(f"成功 {ok}  跳过 {skipped}  失败 {failed}")
    for name, status, detail in results:
        print(f"  {status:<6} {name:<40} {detail}")

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
