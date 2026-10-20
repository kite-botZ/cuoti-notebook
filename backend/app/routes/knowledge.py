"""知识点相关接口 + 大模型自动打标。

接口一览：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET  | `/api/knowledge-points` | 列出知识点（可按学科过滤，支持树形） |
| POST | `/api/knowledge-points` | 手动新增知识点 |
| GET  | `/api/questions/{id}/knowledge-points` | 查某道题的知识点 |
| PUT  | `/api/questions/{id}/knowledge-points` | 手动设置某道题的知识点 |
| POST | `/api/banks/{bank_id}/questions/auto-tag` | **调用大模型批量打标**（本步重点） |

## 为什么 auto-tag 是同步接口

打标是重活儿（每题要跑一次模型推理），但做成异步任务队列会让这一步的依赖变多。
这里先用「同步 + limit 限制」的方式：一次最多标 `limit` 道，
跑完返回统计。接口用同步 `def` 声明，FastAPI 会自动把它丢进线程池，
不会阻塞事件循环里的其它请求。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.knowledge import (
    DEFAULT_BATCH_SIZE,
    apply_tags,
    get_or_create_kp,
    normalize_kp_name,
    is_useful_kp,
    tag_questions,
)
from app.models import KnowledgePoint, Question, QuestionKnowledgePoint
from app.routes.ai import AI_API_BASE, AI_MODEL
from app.routes.banks import bank_for_user, current_user_id, ensure_question_owned

router = APIRouter(prefix="/api", tags=["knowledge"])


# ============================================================
# 请求体
# ============================================================

class KpCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    subject: str = Field(default="综合", min_length=1, max_length=50)
    parent_id: int | None = None
    description: str = Field(default="", max_length=255)


class KpItem(BaseModel):
    name: str
    weight: float = 1.0


class SetQuestionKps(BaseModel):
    knowledge_points: list[KpItem] = Field(default_factory=list)


# ============================================================
# 知识点 CRUD
# ============================================================

@router.get("/knowledge-points")
def list_knowledge_points(
    subject: str | None = None,
    tree: bool = False,
    db: Session = Depends(get_db),
):
    """列出知识点。`tree=true` 时返回嵌套结构，否则返回扁平列表。"""
    query = db.query(KnowledgePoint)
    if subject:
        query = query.filter(KnowledgePoint.subject == subject)
    rows = query.order_by(KnowledgePoint.subject, KnowledgePoint.name).all()

    def payload(kp: KnowledgePoint) -> dict:
        return {
            "id": kp.id,
            "name": kp.name,
            "subject": kp.subject,
            "parent_id": kp.parent_id,
            "description": kp.description,
        }

    if not tree:
        return [payload(kp) for kp in rows]

    nodes = {kp.id: {**payload(kp), "children": []} for kp in rows}
    roots: list[dict] = []
    for kp in rows:
        node = nodes[kp.id]
        parent = nodes.get(kp.parent_id) if kp.parent_id else None
        (parent["children"] if parent else roots).append(node)
    return roots


@router.post("/knowledge-points", status_code=201)
def create_knowledge_point(body: KpCreate, db: Session = Depends(get_db)):
    name = normalize_kp_name(body.name)
    if not is_useful_kp(name):
        raise HTTPException(status_code=422, detail="知识点名称太宽泛或为空")

    exists = (
        db.query(KnowledgePoint)
        .filter(KnowledgePoint.subject == body.subject, KnowledgePoint.name == name)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="该学科下已存在同名知识点")

    if body.parent_id is not None:
        parent = db.query(KnowledgePoint).filter(KnowledgePoint.id == body.parent_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="父知识点不存在")

    kp = KnowledgePoint(
        name=name,
        subject=body.subject,
        parent_id=body.parent_id,
        description=body.description,
    )
    db.add(kp)
    db.commit()
    db.refresh(kp)
    return {"id": kp.id, "name": kp.name, "subject": kp.subject, "parent_id": kp.parent_id}


# ============================================================
# 题目 ↔ 知识点
# ============================================================

def _question_kps(db: Session, question_id: int) -> list[dict]:
    rows = (
        db.query(QuestionKnowledgePoint, KnowledgePoint)
        .join(KnowledgePoint, QuestionKnowledgePoint.kp_id == KnowledgePoint.id)
        .filter(QuestionKnowledgePoint.question_id == question_id)
        .order_by(QuestionKnowledgePoint.weight.desc(), KnowledgePoint.name)
        .all()
    )
    return [
        {
            "kp_id": kp.id,
            "name": kp.name,
            "subject": kp.subject,
            "weight": link.weight,
            "source": link.source,
        }
        for link, kp in rows
    ]


@router.get("/questions/{question_id}/knowledge-points")
def get_question_kps(
    question_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    ensure_question_owned(question_id, user_id, db)
    return _question_kps(db, question_id)


@router.put("/questions/{question_id}/knowledge-points")
def set_question_kps(
    question_id: int,
    body: SetQuestionKps,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """手动设置某道题的知识点（会整体覆盖，source 标记为 manual）。"""
    question = ensure_question_owned(question_id, user_id, db)
    bank_subject = _subject_of_question(db, question)

    tags = [{"name": item.name, "weight": item.weight} for item in body.knowledge_points]
    apply_tags(db, question_id, tags, bank_subject, source="manual", replace=True)
    db.commit()
    return {"question_id": question_id, "knowledge_points": _question_kps(db, question_id)}


def _subject_of_question(db: Session, question: Question) -> str:
    from app.models import QuestionBank
    bank = db.query(QuestionBank).filter(QuestionBank.id == question.bank_id).first()
    return bank.subject if bank and bank.subject else "综合"


# ============================================================
# 大模型自动打标
# ============================================================

@router.post("/banks/{bank_id}/questions/auto-tag")
def auto_tag_bank(
    bank_id: int,
    limit: int = 50,
    batch_size: int = DEFAULT_BATCH_SIZE,
    overwrite: bool = False,
    dry_run: bool = False,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """用大模型给题库里的题目标注知识点。

    - `limit`：本次最多处理多少道（模型推理慢，必须限量）
    - `batch_size`：一次请求让模型处理几道
    - `overwrite`：默认只处理**还没标注过**的题，避免重复花时间
    - `dry_run=true`：只返回将要处理多少道 + prompt 预览，不调模型（省钱/调 prompt）
    """
    bank = bank_for_user(bank_id, user_id, db)
    limit = max(1, min(int(limit), 500))
    batch_size = max(1, min(int(batch_size), 50))

    query = db.query(Question).filter(
        Question.bank_id == bank_id, Question.is_archived.is_(False)
    )
    if not overwrite:
        tagged = select(QuestionKnowledgePoint.question_id).where(
            QuestionKnowledgePoint.question_id == Question.id
        )
        query = query.filter(~tagged.exists())

    questions = query.order_by(Question.id).limit(limit).all()

    if not questions:
        return {
            "requested": 0,
            "tagged": 0,
            "links": 0,
            "message": "没有需要标注的题目（都已经标过了，可以用 overwrite=true 重标）",
        }

    if dry_run:
        from app.knowledge import build_tag_prompt
        first_batch = questions[:batch_size]
        return {
            "requested": len(questions),
            "dry_run": True,
            "batches": (len(questions) + batch_size - 1) // batch_size,
            "subject": bank.subject,
            "prompt_preview": build_tag_prompt(first_batch, bank.subject)[:1200],
            "message": f"将处理 {len(questions)} 道题，分 "
                       f"{(len(questions) + batch_size - 1) // batch_size} 批",
        }

    # 延迟导入：没有装 ollama 包时，其它接口仍然能正常用
    try:
        import ollama
    except ImportError:
        raise HTTPException(status_code=503, detail="服务端未安装 ollama 依赖")

    client = ollama.Client(host=AI_API_BASE)
    report = tag_questions(
        db=db,
        questions=questions,
        subject=bank.subject,
        client=client,
        model=AI_MODEL,
        batch_size=batch_size,
        source="llm",
    )
    db.commit()

    report["subject"] = bank.subject
    report["remaining"] = (
        db.query(Question)
        .filter(Question.bank_id == bank_id, Question.is_archived.is_(False))
        .count()
        - db.query(QuestionKnowledgePoint)
        .filter(
            QuestionKnowledgePoint.question_id.in_(
                select(Question.id).where(Question.bank_id == bank_id)
            )
        )
        .distinct()
        .count()
    )
    report["message"] = (
        f"标注完成：{report['tagged']}/{report['requested']} 道，"
        f"建立 {report['links']} 条知识点关联，"
        f"{report['failed_batches']} 批失败"
    )
    return report


@router.get("/banks/{bank_id}/knowledge-coverage")
def knowledge_coverage(
    bank_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """题库的知识点覆盖情况——用来检查「还有多少题没打标签」。

    认知诊断之前必须先确认覆盖率，不然诊断结果会漏掉大量题目。
    """
    bank = bank_for_user(bank_id, user_id, db)

    total = (
        db.query(Question)
        .filter(Question.bank_id == bank_id, Question.is_archived.is_(False))
        .count()
    )
    tagged_qids = (
        db.query(QuestionKnowledgePoint.question_id)
        .join(Question, Question.id == QuestionKnowledgePoint.question_id)
        .filter(Question.bank_id == bank_id, Question.is_archived.is_(False))
        .distinct()
        .count()
    )
    kp_count = (
        db.query(QuestionKnowledgePoint.kp_id)
        .join(Question, Question.id == QuestionKnowledgePoint.question_id)
        .filter(Question.bank_id == bank_id)
        .distinct()
        .count()
    )
    return {
        "bank_id": bank_id,
        "subject": bank.subject,
        "questions_total": total,
        "questions_tagged": tagged_qids,
        "questions_untagged": total - tagged_qids,
        "coverage": round(tagged_qids / total, 4) if total else 0.0,
        "knowledge_points_used": kp_count,
    }
