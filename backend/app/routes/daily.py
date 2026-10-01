"""每日目标与打卡数据。

打卡规则：当天只要答过至少 1 道题，就算打卡。
连续打卡：从今天（或昨天）往前推，每天都有答题记录的最长天数。
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AnswerAttempt, UserSettings
from app.routes.banks import current_user_id

router = APIRouter(prefix="/api/daily", tags=["daily"])

DEFAULT_GOAL = 20


class GoalBody(BaseModel):
    daily_goal: int = Field(ge=1, le=500)


def get_or_create_settings(user_id: int, db: Session) -> UserSettings:
    s = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    if not s:
        s = UserSettings(user_id=user_id, daily_goal=DEFAULT_GOAL)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


@router.get("/summary")
def daily_summary(
    days: int = Query(30, ge=7, le=90),
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """
    返回今日数据 + 最近 N 天的打卡记录 + 连续打卡天数。
    """
    settings = get_or_create_settings(user_id, db)
    goal = settings.daily_goal

    today = datetime.now().date()
    start = today - timedelta(days=days - 1)

    # 查出范围内每天的答题数
    rows = (
        db.query(
            func.date(AnswerAttempt.answered_at).label("d"),
            func.count(AnswerAttempt.id).label("cnt"),
        )
        .filter(
            AnswerAttempt.user_id == user_id,
            func.date(AnswerAttempt.answered_at) >= start,
        )
        .group_by(func.date(AnswerAttempt.answered_at))
        .all()
    )

    # 转成字典：{ "2026-09-19": 12, ... }
    count_map = {}
    for row in rows:
        key = row.d.isoformat() if hasattr(row.d, "isoformat") else str(row.d)
        count_map[key] = int(row.cnt or 0)

    # 组装最近 N 天
    days_list = []
    for i in range(days):
        day = start + timedelta(days=i)
        key = day.isoformat()
        cnt = count_map.get(key, 0)
        days_list.append({
            "date": key,
            "count": cnt,
            "reached": cnt >= goal,
            "checked_in": cnt > 0,
        })

    today_count = count_map.get(today.isoformat(), 0)

    # 计算连续打卡天数
    streak = 0
    check_day = today
    # 今天还没打卡时，从昨天开始算
    if count_map.get(check_day.isoformat(), 0) == 0:
        check_day = today - timedelta(days=1)

    while True:
        key = check_day.isoformat()
        if count_map.get(key, 0) > 0:
            streak += 1
            check_day -= timedelta(days=1)
        else:
            break
        if streak > 9999:
            break

    return {
        "today_count": today_count,
        "daily_goal": goal,
        "today_reached": today_count >= goal,
        "streak": streak,
        "days": days_list,
    }


@router.put("/goal")
def update_goal(
    body: GoalBody,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """修改每日目标。"""
    settings = get_or_create_settings(user_id, db)
    settings.daily_goal = body.daily_goal
    db.commit()
    return {"message": "目标已更新", "daily_goal": settings.daily_goal}