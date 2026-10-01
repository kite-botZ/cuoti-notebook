"""学习数据统计接口。

数据全部来自 answer_attempts（答题历史），
不额外建表、不缓存——因为数据量小，实时算最快。
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AnswerAttempt, Question, QuestionBank
from app.routes.banks import current_user_id

router = APIRouter(prefix="/api/stats", tags=["stats"])


# ============================================================
# 总览：累计答题数 / 正确率 / 学习天数
# ============================================================

@router.get("/overview")
def overview(
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    total = (
        db.query(func.count(AnswerAttempt.id))
        .filter(AnswerAttempt.user_id == user_id)
        .scalar()
        or 0
    )

    correct = (
        db.query(func.count(AnswerAttempt.id))
        .filter(
            AnswerAttempt.user_id == user_id,
            AnswerAttempt.is_correct.is_(True),
        )
        .scalar()
        or 0
    )

    # 学习天数：不同日期的数量
    active_days = (
        db.query(func.count(func.distinct(func.date(AnswerAttempt.answered_at))))
        .filter(AnswerAttempt.user_id == user_id)
        .scalar()
        or 0
    )

    return {
        "total_attempts": total,
        "correct_attempts": correct,
        "accuracy": round(correct / total, 4) if total else 0,
        "active_days": active_days,
    }


# ============================================================
# 最近 N 天趋势
# ============================================================

@router.get("/trend")
def trend(
    days: int = Query(7, ge=1, le=90),
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """
    返回最近 N 天的答题数、正确数、正确率。
    没有数据的天也会返回（计数为 0），方便前端画连续的折线。
    """
    today = datetime.now().date()
    start = today - timedelta(days=days - 1)

    # 用 CASE WHEN 把 boolean 转成 0/1 再求和
    correct_expr = func.sum(
        case((AnswerAttempt.is_correct.is_(True), 1), else_=0)
    )

    rows = (
        db.query(
            func.date(AnswerAttempt.answered_at).label("d"),
            func.count(AnswerAttempt.id).label("total"),
            correct_expr.label("correct"),
        )
        .filter(
            AnswerAttempt.user_id == user_id,
            func.date(AnswerAttempt.answered_at) >= start,
        )
        .group_by(func.date(AnswerAttempt.answered_at))
        .all()
    )

    # 把结果转成字典，方便按日期查
    data = {}
    for row in rows:
        d = row.d
        # MySQL 返回的可能是 date，也可能被 SQLAlchemy 转成 str
        if hasattr(d, "isoformat"):
            key = d.isoformat()
        else:
            key = str(d)
        data[key] = (int(row.total or 0), int(row.correct or 0))

    # 补齐空白日期
    result = []
    for i in range(days):
        day = start + timedelta(days=i)
        key = day.isoformat()
        total, correct = data.get(key, (0, 0))
        result.append({
            "date": key,
            "total": total,
            "correct": correct,
            "accuracy": round(correct / total, 4) if total else 0,
        })

    return result


# ============================================================
# 各题库正确率
# ============================================================

@router.get("/banks")
def bank_stats(
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """
    每个题库的答题总数和正确数。
    只返回有答题记录的题库。
    """
    correct_expr = func.sum(
        case((AnswerAttempt.is_correct.is_(True), 1), else_=0)
    )

    rows = (
        db.query(
            QuestionBank.id,
            QuestionBank.name,
            QuestionBank.subject,
            func.count(AnswerAttempt.id).label("total"),
            correct_expr.label("correct"),
        )
        .join(Question, Question.bank_id == QuestionBank.id)
        .join(AnswerAttempt, AnswerAttempt.question_id == Question.id)
        .filter(
            QuestionBank.user_id == user_id,
            AnswerAttempt.user_id == user_id,
        )
        .group_by(QuestionBank.id, QuestionBank.name, QuestionBank.subject)
        .order_by(func.count(AnswerAttempt.id).desc())
        .all()
    )

    return [
        {
            "bank_id": row.id,
            "name": row.name,
            "subject": row.subject,
            "total": int(row.total or 0),
            "correct": int(row.correct or 0),
            "accuracy": round((row.correct or 0) / row.total, 4) if row.total else 0,
        }
        for row in rows
    ]