"""练习进度：保存和恢复。

为什么需要它：用户刷题中途关掉浏览器，回来应该能接着刷，
而不是从第 1 题重新开始。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PracticeSession, QuestionBank
from app.routes.banks import current_user_id

router = APIRouter(prefix="/api/practice", tags=["practice"])


class SaveProgressBody(BaseModel):
    bank_id: int
    source: str = Field(min_length=1, max_length=20)
    question_ids: list[int]
    answers: dict = Field(default_factory=dict)
    current_index: int = 0


def _ensure_bank_owned(bank_id: int, user_id: int, db: Session) -> None:
    """校验题库属于当前用户。

    三个端点（GET/PUT/DELETE）都要校验。原来只有 PUT 校验了：
    GET/DELETE 直接按 `user_id` 过滤 `practice_sessions`，看起来"查不到别人的数据"，
    但 `bank_id` 是攻击者可控的入参——他可以用别人的 `bank_id` 去问
    "我有没有这个题库的进度"，返回值就能确认这个 id 是否存在，
    也是一条不该存在的越权面。更重要的是三个端点的口径必须一致，
    否则"PUT 说没有权限、GET 说没有记录"这种不一致会误导前端。
    """
    bank = (
        db.query(QuestionBank)
        .filter(QuestionBank.id == bank_id, QuestionBank.user_id == user_id)
        .first()
    )
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")


@router.get("/progress")
def get_progress(
    bank_id: int,
    source: str,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """读取上次练习进度。没有则返回 progress=None。"""
    _ensure_bank_owned(bank_id, user_id, db)

    row = (
        db.query(PracticeSession)
        .filter(
            PracticeSession.user_id == user_id,
            PracticeSession.bank_id == bank_id,
            PracticeSession.source == source,
        )
        .first()
    )
    if not row:
        return {"progress": None}

    return {
        "progress": {
            "question_ids": row.question_ids,
            "answers": row.answers,
            "current_index": row.current_index,
        }
    }


@router.put("/progress")
def save_progress(
    body: SaveProgressBody,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """保存练习进度。有则更新，无则创建。"""
    _ensure_bank_owned(body.bank_id, user_id, db)

    row = (
        db.query(PracticeSession)
        .filter(
            PracticeSession.user_id == user_id,
            PracticeSession.bank_id == body.bank_id,
            PracticeSession.source == body.source,
        )
        .first()
    )

    if row:
        row.question_ids = body.question_ids
        row.answers = body.answers
        row.current_index = body.current_index
    else:
        row = PracticeSession(
            user_id=user_id,
            bank_id=body.bank_id,
            source=body.source,
            question_ids=body.question_ids,
            answers=body.answers,
            current_index=body.current_index,
        )
        db.add(row)

    db.commit()
    return {"message": "进度已保存"}


@router.delete("/progress")
def delete_progress(
    bank_id: int,
    source: str,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """练习完成或用户选择"重新开始"时清除进度。"""
    _ensure_bank_owned(bank_id, user_id, db)

    db.query(PracticeSession).filter(
        PracticeSession.user_id == user_id,
        PracticeSession.bank_id == bank_id,
        PracticeSession.source == source,
    ).delete()
    db.commit()
    return {"message": "进度已清除"}