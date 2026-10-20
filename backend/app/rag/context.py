"""把检索结果变成 prompt 上下文 + 前端可以展示的引用列表。

## 为什么要单独一层

「检索到片段」和「让模型照着片段讲」之间还有不少活儿：

1. **查询怎么构造**：直接拿题干去检索，长题干里的干扰词会稀释 BM25。
   把题干、选项、以及这道题的**知识点名称**拼在一起，命中率明显更高
   （知识点本身就是教材里的说法）。
2. **上下文怎么截断**：模型上下文有限，片段太多反而稀释重点；
   而且必须给每个片段加编号，模型才能引用。
3. **引用怎么对上号**：prompt 里的 `[1]` 必须和前端展示的 `sources[0]` 严格一致，
   否则用户点开引用会对不上原文——这里用同一个列表一次性生成，杜绝错位。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import KnowledgePoint, Question, QuestionKnowledgePoint

# 塞进 prompt 的上下文总长度上限（中文字符）
CONTEXT_MAX_CHARS = 1200
# 单个片段最多取多少字
CHUNK_MAX_CHARS = 380
# 查询最多用多少字（太长的题干反而降低召回）
QUERY_MAX_CHARS = 400


def kp_names_for_question(db: Session, question_id: int) -> list[str]:
    """取这道题已标注的知识点名称，用来增强检索查询。"""
    rows = (
        db.query(KnowledgePoint.name)
        .join(QuestionKnowledgePoint, QuestionKnowledgePoint.kp_id == KnowledgePoint.id)
        .filter(QuestionKnowledgePoint.question_id == question_id)
        .order_by(QuestionKnowledgePoint.weight.desc())
        .limit(5)
        .all()
    )
    return [r[0] for r in rows]


def build_query(question: Question, kp_names: list[str] | None = None) -> str:
    """构造检索查询。

    知识点名称放在**最前面**：BM25 对词频敏感，前置高价值词能提高它
    在排序里的权重（很多实现会 ignore 顺序，但放前面没有坏处）。
    """
    parts: list[str] = []
    if kp_names:
        parts.extend(kp_names)
    parts.append(str(question.stem or ""))
    if question.options:
        parts.extend(str(o) for o in (question.options or [])[:4])
    query = " ".join(p.strip() for p in parts if p and p.strip())
    return query[:QUERY_MAX_CHARS]


def format_context(hits: list[dict]) -> tuple[str, list[dict]]:
    """把命中片段格式化成 prompt 上下文，同时返回引用列表。

    返回 `(上下文文本, sources)`，`sources[i]` 对应 prompt 里的 `[i+1]`。
    两者在同一次循环里生成，编号不会错位。
    """
    if not hits:
        return "", []

    blocks: list[str] = []
    sources: list[dict] = []
    used = 0

    for i, hit in enumerate(hits, 1):
        text = " ".join(str(hit.get("text", "")).split())
        if not text:
            continue
        text = text[:CHUNK_MAX_CHARS]
        if used + len(text) > CONTEXT_MAX_CHARS:
            break

        source_label = (hit.get("title") or f"文档#{hit.get('doc_id')}")
        chapter = hit.get("chapter") or ""
        page = hit.get("page")
        header = f"[{i}] 《{source_label}》"
        if chapter:
            header += f" {chapter}"
        if page:
            header += f" 第{page}页"

        blocks.append(f"{header}\n{text}")
        sources.append({
            "index": i,
            "chunk_id": hit.get("chunk_id"),
            "doc_id": hit.get("doc_id"),
            "title": source_label,
            "chapter": chapter,
            "page": page,
            "score": hit.get("score"),
            "coverage": hit.get("coverage"),
            "preview": text[:120],
        })
        used += len(text) + len(header)

    return "\n\n".join(blocks), sources


CITATION_RULES = """【教材参考片段】
{context}

【引用规则 — 必须遵守】
1. 上面的片段来自用户自己上传的教材/讲义，是你回答的主要依据。
2. 引用某个片段的观点时，在句末用编号标注来源，例如「……这就是文段的主体一致。[1]」
3. 片段里没有的内容，不要写成「教材说」——那等于编造。
4. 如果片段与本题无关，直接忽略它们，按你自己的知识回答，不要硬凑引用。
5. 不要整段照抄片段，要结合题目本身讲清楚。
"""


def render_context_block(context: str) -> str:
    """生成带引用规则的 prompt 片段；没有上下文时返回空串。"""
    if not context:
        return ""
    return CITATION_RULES.format(context=context) + "\n"
