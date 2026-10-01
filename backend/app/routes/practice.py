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


@router.get("/progress")
def get_progress(
    bank_id: int,
    source: str,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """读取上次练习进度。没有则返回 progress=None。"""
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
    # 校验题库归属，防止越权
    bank = (
        db.query(QuestionBank)
        .filter(QuestionBank.id == body.bank_id, QuestionBank.user_id == user_id)
        .first()
    )
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")

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
    db.query(PracticeSession).filter(
        PracticeSession.user_id == user_id,
        PracticeSession.bank_id == bank_id,
        PracticeSession.source == source,
    ).delete()
    db.commit()
    return {"message": "进度已清除"}