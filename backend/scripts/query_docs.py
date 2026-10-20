"""在命令行里试检索效果，用来调参和看召回质量。

用法：

    python scripts/query_docs.py "中心理解题的总原则是什么" --top 3
    python scripts/query_docs.py "细节判断题 偷换概念" --subject 行测 --alpha 0.6

会打印每个命中片段的：综合分 / BM25 分 / 向量分 / 章节 / 页码 / 正文前若干字。
调节 `--alpha` 可以直接看出「纯关键词」和「纯语义」的差别：
    --alpha 0   纯 BM25
    --alpha 1   纯向量（需要装了 embedding 模型）
    --alpha 0.5 混合
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    p = argparse.ArgumentParser(description="知识库检索调试")
    p.add_argument("query")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--alpha", type=float, default=0.5)
    p.add_argument("--subject", default=None)
    p.add_argument("--width", type=int, default=120, help="每段显示多少字")
    args = p.parse_args()

    os.environ.setdefault("APP_ENV", "production")
    sys.path.insert(0, str(BACKEND_DIR))

    from app.db import Base, SessionLocal, engine
    from app import models  # noqa: F401
    from app.rag.service import retrieve

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        result = retrieve(
            db=db, query=args.query, top_k=args.top,
            subject=args.subject, alpha=args.alpha,
        )
    finally:
        db.close()

    if "message" in result:
        print(result["message"])
    print(f"\n查询：{args.query!r}")
    print(f"检索模式：{result['mode']}   候选 {result['candidates']} 段   "
          f"embed_model={result.get('embed_model') or '(无)'}\n")

    if not result["hits"]:
        print("没有命中。可能是语料里确实没有相关内容，或者过滤条件太严。")
        return 0

    for i, hit in enumerate(result["hits"], 1):
        text = " ".join(hit["text"].split())[:args.width]
        print(f"--- 命中 {i}  综合 {hit['score']:.3f}  "
              f"BM25 {hit['bm25_score']:.3f}  向量 {hit['vector_score']:.3f}  "
              f"词命中率 {hit.get('coverage', 0):.2f}")
        print(f"    章节：{hit.get('chapter') or '(无)'}   页码：{hit.get('page') or '-'}")
        print(f"    正文：{text}…")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
