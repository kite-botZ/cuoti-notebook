"""认知诊断接口：知识点掌握度 + 自适应选题。

这里不重复实现诊断逻辑，路由只做三件事：鉴权校验、调用 `app.mastery`、
把 ORM 对象转成和题目列表接口**同样结构**的 JSON。

最后一点不是小事：自适应选题返回的题目如果字段和 `/banks/{id}/questions`
不一致，Practice.vue 就得为它写一套单独的解析和状态补全逻辑，
两边迟早会漂移（比如一边带 `note` 一边不带）。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import bkt
from app.db import get_db
from app.mastery import (
    available_ids_select,
    mastery_overview,
    pick_adaptive,
)
from app.models import KnowledgePoint, QuestionKnowledgePoint, UserKpMastery
from app.routes.banks import (
    bank_for_user,
    current_user_id,
    question_payload_with_state,
    states_for,
)

router = APIRouter(prefix="/api", tags=["mastery"])


@router.get("/banks/{bank_id}/mastery")
def get_mastery(
    bank_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """题库下所有知识点的掌握度（BKT 后验），最弱的排前面。

    没做过的知识点也会列出来，`p_known` 是 BKT 的初始值 `p_init`，
    `practiced=false`。诊断的价值一半在于指出"哪些还没掌握"。
    """
    bank_for_user(bank_id, user_id, db)
    return mastery_overview(db, user_id, bank_id)


@router.get("/banks/{bank_id}/adaptive-questions")
def get_adaptive_questions(
    bank_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """按掌握度最低的知识点挑接下来该做的题。

    返回的 `picked` 每项都带 `reason`，说明为什么选中它——
    自适应如果只给结果不给理由，用户没法判断它是不是在乱推。

    `strategy` 有三种取值，前端据此提示：
    - `bkt_adaptive`：完全按认知诊断出的薄弱知识点选
    - `bkt_adaptive_with_fill`：薄弱知识点的题不够，用未做过的题补齐
    - `no_kp_fallback`：题库没有任何知识点标注，退化成本做过的题优先
    """
    bank_for_user(bank_id, user_id, db)
    report = pick_adaptive(db, user_id, bank_id, limit)

    question_ids = [p["question"].id for p in report["picked"]]
    states = states_for(user_id, question_ids, db)

    items = []
    for p in report["picked"]:
        q = p["question"]
        items.append({
            **question_payload_with_state(q, states.get(q.id), include_answer=True),
            # 诊断信息挂在题目上：前端显示"为什么是这道题"不用再查一次接口
            "kp_id": p["kp_id"],
            "reason": p["reason"],
            "kp_weight": p["weight"],
            "attempts": p["attempts"],
            "wrong_count": p["wrong_count"],
        })

    report["picked"] = items
    return report


@router.get("/banks/{bank_id}/mastery/summary")
def get_mastery_summary(
    bank_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """只需要总体情况时的轻量接口：不返回每个知识点的明细。

    题库页顶部要显示"平均掌握度 / 最弱的知识点"，没必要为此传几十条明细。
    """
    bank_for_user(bank_id, user_id, db)
    overview = mastery_overview(db, user_id, bank_id)
    overview.pop("items", None)
    return overview


@router.delete("/banks/{bank_id}/mastery")
def reset_mastery(
    bank_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """清空本人在这个题库涉及的知识点上的掌握度，用于重新演示 / 重新诊断。

    只删**本人**的 `user_kp_mastery` 行，不动 `answer_attempts`：
    作答历史是事实，不该为了重跑诊断而抹掉。删除后掌握度回到 `p_init`，
    想从历史重建的话按作答时间顺序重放即可。
    """
    bank_for_user(bank_id, user_id, db)

    kp_ids = [
        r[0]
        for r in db.query(QuestionKnowledgePoint.kp_id)
        .filter(QuestionKnowledgePoint.question_id.in_(available_ids_select(db, bank_id, user_id)))
        .distinct()
        .all()
    ]
    if not kp_ids:
        return {"deleted": 0, "kp_count": 0, "message": "这个题库还没有知识点标注"}

    deleted = (
        db.query(UserKpMastery)
        .filter(UserKpMastery.user_id == user_id, UserKpMastery.kp_id.in_(kp_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return {
        "deleted": int(deleted or 0),
        "kp_count": len(kp_ids),
        "message": f"已重置 {deleted} 个知识点的掌握度（作答历史保留）",
    }


@router.get("/knowledge-points/{kp_id}/mastery")
def get_kp_mastery(
    kp_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """单个知识点的掌握度明细。

    知识点是全局共享的，但掌握度是私有的，所以这里不校验知识点归属，
    只查"我"的那一行；查不到就返回初始值。
    """
    kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == kp_id).first()
    if not kp:
        raise HTTPException(status_code=404, detail="知识点不存在")

    row = (
        db.query(UserKpMastery)
        .filter(UserKpMastery.user_id == user_id, UserKpMastery.kp_id == kp_id)
        .first()
    )
    p = row.p_known if row and row.p_known is not None else bkt.DEFAULT_PARAMS.p_init
    return {
        "kp_id": kp.id,
        "name": kp.name,
        "subject": kp.subject,
        "parent_id": kp.parent_id,
        "p_known": round(p, 4),
        "level": bkt.level(p),
        "attempts": (row.attempts or 0) if row else 0,
        "correct": (row.correct or 0) if row else 0,
        "practiced": bool(row and (row.attempts or 0) > 0),
        "last_answered_at": (
            int(row.last_answered_at.timestamp()) if row and row.last_answered_at else None
        ),
    }