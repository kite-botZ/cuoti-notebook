"""认知诊断与自适应选题：把 `bkt.py` 的公式接到数据库上。

这个模块只做三件事：

1. `record_attempt`：一次作答 → 更新这道题关联的每个知识点的掌握度（增量）。
   由 `POST /api/questions/{id}/answer` 调用。
2. `mastery_overview`：某个题库下所有知识点的掌握度，给前端画进度条。
3. `pick_adaptive`：挑接下来该做的题——按掌握度最低的知识点选。

关于"选哪些题"，这里刻意没有上强化学习或 Bandit：
在只有几百次作答的数据量下，任何自学习的选题策略都学不到东西，
但会让结果不可解释、也没法在测试里断言。当前策略是**规则 + 掌握度排序**，
每一步都能说清楚为什么选它，等作答数据积累够了再谈更复杂的策略。

## 口径统一

"这道题能不能拿来练"（未归档 + 未斩题）在这个模块里只有一个实现
`available_questions_query()`。掌握度页面、自适应选题、补齐逻辑全部走它，
免得三个地方各写一遍过滤条件、然后对不上。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app import bkt
from app.models import (
    AnswerAttempt,
    KnowledgePoint,
    Question,
    QuestionKnowledgePoint,
    QuestionUserState,
    UserKpMastery,
)

# 一次自适应选题最多看多少个知识点。掌握度最低的前 N 个作为本次训练目标，
# 不是只看第 1 个：只盯一个知识点，训练集会退化成"同一种题连做 20 遍"，
# 那是刷题量，不是诊断。
MAX_TARGET_KPS = 8

# 每个目标知识点先捞多少道候选进内存排序。够排序用即可，
# 两万题的题库里不能把某个知识点下的题全拉出来。
CANDIDATES_PER_KP = 12


def _now() -> datetime:
    return datetime.now()


def available_questions_query(db: Session, bank_id: int, user_id: int):
    """题库里"能拿来练"的题：未归档 + 未被本人斩题。

    `QuestionUserState` 的关联条件必须把 `user_id` 写进 ON 里，不能塞进 WHERE：
    - 塞进 WHERE：`user_id = ?` 会让 LEFT JOIN 退化成 INNER JOIN，
      一道题只要本人还没建过 state 行就被过滤掉——而绝大多数题都没 state 行。
    - 不写 user_id：会关联到**别人**的斩题状态，别人斩了我也做不了。
    """
    return (
        db.query(Question.id)
        .outerjoin(
            QuestionUserState,
            and_(
                QuestionUserState.question_id == Question.id,
                QuestionUserState.user_id == user_id,
            ),
        )
        .filter(
            Question.bank_id == bank_id,
            Question.is_archived.is_(False),
            QuestionUserState.is_cut.isnot(True),
        )
    )


def available_ids_select(db: Session, bank_id: int, user_id: int):
    """可用题 id 的子查询，可以直接放进 `Question.id.in_(...)`。

    单独抽一层是因为 `Query` 没有 `.select()`（只有 `Subquery` 有）。
    之前在图省事的地方直接对 `Query` 调 `.select()`，于是降级补齐那条路径
    一走到就 AttributeError——正常路径用不到它，所以单元测试不跑降级就发现不了。
    """
    return available_questions_query(db, bank_id, user_id).subquery().select()


# ============================================================
# 1. 作答 → 更新掌握度
# ============================================================

def get_or_create_mastery(user_id: int, kp_id: int, db: Session) -> UserKpMastery:
    row = (
        db.query(UserKpMastery)
        .filter(UserKpMastery.user_id == user_id, UserKpMastery.kp_id == kp_id)
        .first()
    )
    if row:
        return row
    row = UserKpMastery(
        user_id=user_id,
        kp_id=kp_id,
        p_known=bkt.DEFAULT_PARAMS.p_init,
        attempts=0,
        correct=0,
    )
    db.add(row)
    return row


def record_attempt(
    db: Session,
    user_id: int,
    question: Question,
    is_correct: bool,
) -> list[dict]:
    """把一次作答的影响写到该题关联的每个知识点上。

    返回本次每个知识点的掌握度变化，前端可以直接显示"这道题让
    「TCP 拥塞控制」从 0.42 涨到 0.53"——诊断是不是真的在动，看得见。

    注意：调用方负责 `db.commit()`。这里不提交，是为了让"写答题历史 +
    更新错题计数 + 更新掌握度"落在同一个事务里，避免只写了一半。
    """
    links = (
        db.query(QuestionKnowledgePoint)
        .filter(QuestionKnowledgePoint.question_id == question.id)
        .all()
    )
    if not links:
        # 这道题还没标注知识点。不是错误：题库可能只标注了一部分，
        # 提示前端去跑自动标注即可，不能因为没标签就拒绝判题。
        return []

    changes: list[dict] = []
    now = _now()

    for link in links:
        m = get_or_create_mastery(user_id, link.kp_id, db)
        before = m.p_known if m.p_known is not None else bkt.DEFAULT_PARAMS.p_init
        after = bkt.apply_attempt(before, is_correct, link.weight)

        m.p_known = after
        m.attempts = (m.attempts or 0) + 1
        if is_correct:
            m.correct = (m.correct or 0) + 1
        m.last_answered_at = now

        changes.append({
            "kp_id": link.kp_id,
            "p_before": round(before, 4),
            "p_after": round(after, 4),
            "delta": round(after - before, 4),
            "weight": link.weight,
            "level": bkt.level(after),
        })

    return changes


def attach_kp_names(db: Session, changes: list[dict]) -> list[dict]:
    """给变化列表补上知识点名字，直接可以返回给前端。"""
    if not changes:
        return []
    names = dict(
        db.query(KnowledgePoint.id, KnowledgePoint.name)
        .filter(KnowledgePoint.id.in_([c["kp_id"] for c in changes]))
        .all()
    )
    for c in changes:
        c["name"] = names.get(c["kp_id"], f"知识点 {c['kp_id']}")
    return changes


# ============================================================
# 2. 掌握度总览
# ============================================================

def _kp_rows_for_bank(db: Session, bank_id: int, user_id: int) -> list[dict]:
    """题库里被考到的知识点，以及各自有多少道可用题。

    题量口径和自适应选题一致（都走 `available_questions_query`）。
    两个接口口径不一致的话，会出现"掌握度页面说有 30 道题可练，
    点自适应刷题只出来 3 道"这种对不上的情况。
    """
    rows = (
        db.query(
            KnowledgePoint.id,
            KnowledgePoint.name,
            KnowledgePoint.parent_id,
            KnowledgePoint.subject,
            func.count(func.distinct(QuestionKnowledgePoint.question_id)),
        )
        .join(QuestionKnowledgePoint, QuestionKnowledgePoint.kp_id == KnowledgePoint.id)
        .filter(QuestionKnowledgePoint.question_id.in_(available_ids_select(db, bank_id, user_id)))
        .group_by(
            KnowledgePoint.id,
            KnowledgePoint.name,
            KnowledgePoint.parent_id,
            KnowledgePoint.subject,
        )
        .order_by(KnowledgePoint.id)
        .all()
    )
    return [
        {
            "kp_id": r[0],
            "name": r[1],
            "parent_id": r[2],
            "subject": r[3],
            "question_count": int(r[4] or 0),
        }
        for r in rows
    ]


def _mastery_map(db: Session, user_id: int, kp_ids: list[int]) -> dict[int, UserKpMastery]:
    if not kp_ids:
        return {}
    rows = (
        db.query(UserKpMastery)
        .filter(UserKpMastery.user_id == user_id, UserKpMastery.kp_id.in_(kp_ids))
        .all()
    )
    return {r.kp_id: r for r in rows}


def mastery_overview(db: Session, user_id: int, bank_id: int) -> dict:
    """题库下所有知识点的掌握度，从最弱到最强排序。

    没做过的知识点**也要返回**，`p_known` 取 `p_init`：
    诊断的价值一半在于指出"哪些还没掌握"，只列做过的知识点等于把
    "没练过"直接抹掉了，那样自适应选题就没有冷启动目标。
    """
    kp_rows = _kp_rows_for_bank(db, bank_id, user_id)
    mastery = _mastery_map(db, user_id, [r["kp_id"] for r in kp_rows])

    items: list[dict] = []
    for r in kp_rows:
        m = mastery.get(r["kp_id"])
        p = m.p_known if m and m.p_known is not None else bkt.DEFAULT_PARAMS.p_init
        attempts = (m.attempts or 0) if m else 0
        correct = (m.correct or 0) if m else 0
        items.append({
            **r,
            "p_known": round(p, 4),
            "level": bkt.level(p),
            "need": round(bkt.need(p), 4),
            "attempts": attempts,
            "correct": correct,
            # 正确率和掌握度一起给：两个数不一致时（正确率高但掌握度低）
            # 恰恰是最该看的信号，说明这个知识点是蒙对的
            "accuracy": round(correct / attempts, 4) if attempts else None,
            "practiced": attempts > 0,
            "last_answered_at": (
                int(m.last_answered_at.timestamp()) if m and m.last_answered_at else None
            ),
        })

    # 最弱的排前面——前端直接按顺序渲染，不用再排一次
    items.sort(key=lambda x: (x["p_known"], x["kp_id"]))

    practiced = [i for i in items if i["practiced"]]
    overall = round(sum(i["p_known"] for i in items) / len(items), 4) if items else None
    return {
        "bank_id": bank_id,
        "kp_count": len(items),
        "practiced_count": len(practiced),
        "untouched_count": len(items) - len(practiced),
        "overall_p_known": overall,
        "overall_level": bkt.level(overall) if overall is not None else None,
        "weakest": items[0] if items else None,
        "params": {
            "p_init": bkt.DEFAULT_PARAMS.p_init,
            "p_learn": bkt.DEFAULT_PARAMS.p_learn,
            "p_slip": bkt.DEFAULT_PARAMS.p_slip,
            "p_guess": bkt.DEFAULT_PARAMS.p_guess,
        },
        "items": items,
    }


# ============================================================
# 3. 自适应选题
# ============================================================

def _attempt_stats(db: Session, user_id: int, question_ids: list[int]) -> dict[int, dict]:
    """这批题各自被做过几次、错过几次。

    自适应选题偏爱"没做过"的题（探索）和"错过"的题（巩固）。
    先按题目 id 批量聚合两次，避免在候选循环里逐题查库（N+1）。
    候选集最多 8 × 12 = 96 道，两次聚合查询完全够用。
    """
    if not question_ids:
        return {}
    attempted = dict(
        db.query(AnswerAttempt.question_id, func.count(AnswerAttempt.id))
        .filter(
            AnswerAttempt.user_id == user_id,
            AnswerAttempt.question_id.in_(question_ids),
        )
        .group_by(AnswerAttempt.question_id)
        .all()
    )
    wrong = dict(
        db.query(AnswerAttempt.question_id, func.count(AnswerAttempt.id))
        .filter(
            AnswerAttempt.user_id == user_id,
            AnswerAttempt.question_id.in_(question_ids),
            AnswerAttempt.is_correct.is_(False),
        )
        .group_by(AnswerAttempt.question_id)
        .all()
    )
    return {
        qid: {"attempts": int(cnt or 0), "wrong": int(wrong.get(qid, 0))}
        for qid, cnt in attempted.items()
    }


def _score_candidate(stats: dict, wrong_count: int) -> float:
    """候选题的优先级分数，越大越先做。

    - 没做过的题优先（探索）：做过 0 次满分，3 次及以上得 0 分
    - 错过的题加权（巩固）：错 3 次及以上得满加权

    权重取 1.0 : 0.5，是让"没做过"始终压过"错过但做过很多次"。
    诊断需要的是覆盖面；一直重复那几道错题，掌握度估计只会在小样本上打转。
    """
    attempts = stats.get("attempts", 0)
    explore = 1.0 - min(attempts, 3) / 3.0
    exploit = min(max(wrong_count, stats.get("wrong", 0)), 3) / 3.0
    return round(explore + 0.5 * exploit, 4)


def _fill_remaining(
    db: Session,
    user_id: int,
    bank_id: int,
    need: int,
    seen: set[int],
) -> list[Question]:
    """补齐：题库里还没做过（其次做得最少）的题。

    分两阶段，是为了让"没做过优先"这个排序不把整库排序一遍：

    阶段一用 `NOT EXISTS` 反连接 + `ORDER BY id`。它等价于"作答次数 = 0 且按 id 升序"，
    但能走 `(bank_id, is_archived, id)` 索引、凑够 need 条就提前停。
    实测 20911 题：反连接 **33 ms**（`Using index`），
    而直接 `ORDER BY COALESCE(作答次数,0), id` 是 **132 ms**，
    EXPLAIN 里是 `Using temporary; Using filesort`——它先把全库排了一遍。

    阶段二只在"没做过的题不够"时才跑，此时候选集已经小得多，
    再用作答次数排序就不贵了。

    两阶段的结果和"一次按 (作答次数, id) 排序取前 need 条"完全一致：
    阶段一取的正是那次排序排在最前面的那些，顺序也一样。
    """
    if need <= 0:
        return []

    # ---------- 阶段一：完全没做过的题 ----------
    done = (
        db.query(AnswerAttempt.id)
        .filter(
            AnswerAttempt.user_id == user_id,
            AnswerAttempt.question_id == Question.id,
        )
        .exists()
    )
    fresh = (
        db.query(Question)
        .filter(
            Question.id.in_(available_ids_select(db, bank_id, user_id)),
            ~done,
        )
        .order_by(Question.id.asc())
        # 多取 len(seen) 条来抵消下面被过滤掉的已选题，避免凑不够时再查一次
        .limit(need + len(seen))
    )
    rows = [q for q in fresh.all() if q.id not in seen][:need]
    if len(rows) >= need:
        return rows

    # ---------- 阶段二：从做过的题里挑做得最少的 ----------
    picked_ids = {q.id for q in rows}
    attempts = (
        db.query(
            AnswerAttempt.question_id.label("qid"),
            func.count(AnswerAttempt.id).label("cnt"),
        )
        .filter(AnswerAttempt.user_id == user_id)
        .group_by(AnswerAttempt.question_id)
        .subquery()
    )
    more = (
        db.query(Question)
        .join(attempts, attempts.c.qid == Question.id)
        .filter(
            Question.id.in_(available_ids_select(db, bank_id, user_id)),
            Question.id.notin_(seen | picked_ids),
        )
        .order_by(attempts.c.cnt.asc(), Question.id.asc())
        .limit(need - len(rows))
        .all()
    )
    return rows + more


def pick_adaptive(
    db: Session,
    user_id: int,
    bank_id: int,
    limit: int = 20,
) -> dict:
    """挑接下来该做的题。

    流程：

    1. 找出题库里所有被考到的知识点，取用户对它们的掌握度（没做过 = p_init）
    2. 按掌握度升序取前 `MAX_TARGET_KPS` 个（且随 limit 缩放）当本次训练目标
    3. 每个目标知识点捞 `CANDIDATES_PER_KP` 道候选题
    4. 候选题内部按"没做过优先、错过优先"排序
    5. **轮转**着从各个目标知识点取题，直到凑够 limit

    第 5 步的轮转是关键：如果只是把候选合并后按分数排，掌握度最低的那个
    知识点会霸占全部名额，其余薄弱知识点一个都练不到。
    """
    limit = max(1, min(int(limit), 100))

    # --- 1. 知识点 + 题量 ---
    kp_rows = (
        db.query(
            QuestionKnowledgePoint.kp_id,
            func.count(func.distinct(QuestionKnowledgePoint.question_id)),
        )
        .filter(QuestionKnowledgePoint.question_id.in_(available_ids_select(db, bank_id, user_id)))
        .group_by(QuestionKnowledgePoint.kp_id)
        .all()
    )
    if not kp_rows:
        return _fallback_no_kp(db, user_id, bank_id, limit)

    kp_ids = [r[0] for r in kp_rows]
    kp_question_count = {r[0]: int(r[1] or 0) for r in kp_rows}
    mastery = _mastery_map(db, user_id, kp_ids)
    names = dict(
        db.query(KnowledgePoint.id, KnowledgePoint.name)
        .filter(KnowledgePoint.id.in_(kp_ids))
        .all()
    )

    def p_of(kp_id: int) -> float:
        m = mastery.get(kp_id)
        return m.p_known if m and m.p_known is not None else bkt.DEFAULT_PARAMS.p_init

    # --- 2. 最弱的若干知识点当训练目标 ---
    # 目标数同时受两个条件限制：
    # - 不超过 `limit`：轮转取题时每个目标至少要能分到一道，否则排在后面的
    #   目标一个名额都拿不到，等于没被选上。（一开始写成 (limit+2)//3，
    #   limit=3 时只剩 1 个目标，第二、三个薄弱知识点直接饿死，
    #   是靠"轮转要覆盖多个知识点"那条测试发现的。）
    # - 不超过 `MAX_TARGET_KPS`：目标太散、每个只练一道，也形不成诊断。
    ranked = sorted(kp_ids, key=lambda k: (p_of(k), k))
    targets = ranked[: min(MAX_TARGET_KPS, limit, len(ranked))]

    # --- 3. 每个目标知识点捞候选题 ---
    pools: dict[int, list[dict]] = {}
    question_ids: list[int] = []
    for kp_id in targets:
        rows = (
            db.query(Question, QuestionKnowledgePoint.weight, QuestionUserState.wrong_count)
            .join(QuestionKnowledgePoint, QuestionKnowledgePoint.question_id == Question.id)
            .outerjoin(
                QuestionUserState,
                and_(
                    QuestionUserState.question_id == Question.id,
                    QuestionUserState.user_id == user_id,
                ),
            )
            .filter(
                QuestionKnowledgePoint.kp_id == kp_id,
                Question.id.in_(available_ids_select(db, bank_id, user_id)),
            )
            .order_by(Question.id)
            .limit(CANDIDATES_PER_KP)
            .all()
        )
        pools[kp_id] = [
            {"question": q, "weight": float(w or 1.0), "wrong_count": int(wc or 0)}
            for q, w, wc in rows
        ]
        question_ids.extend(q.id for q, _, _ in rows)

    if not question_ids:
        return _fallback_no_kp(db, user_id, bank_id, limit)

    stats = _attempt_stats(db, user_id, list(dict.fromkeys(question_ids)))
    for kp_id, pool in pools.items():
        for item in pool:
            item["score"] = _score_candidate(
                stats.get(item["question"].id, {}), item["wrong_count"]
            )
        pool.sort(key=lambda x: (-x["score"], x["question"].id))

    # --- 4. 轮转取题 ---
    picked: list[dict] = []
    seen: set[int] = set()
    cursor = {kp_id: 0 for kp_id in targets}
    progressed = True
    while len(picked) < limit and progressed:
        progressed = False
        for kp_id in targets:
            if len(picked) >= limit:
                break
            pool = pools.get(kp_id) or []
            i = cursor[kp_id]
            while i < len(pool) and pool[i]["question"].id in seen:
                i += 1
            cursor[kp_id] = i + 1
            if i >= len(pool):
                continue
            progressed = True
            item = pool[i]
            seen.add(item["question"].id)
            picked.append({
                "question": item["question"],
                "kp_id": kp_id,
                "reason": (
                    f"主考「{names.get(kp_id, kp_id)}」"
                    f"（掌握度 {p_of(kp_id):.2f} · {bkt.level(p_of(kp_id))}）"
                ),
                "weight": item["weight"],
                "attempts": stats.get(item["question"].id, {}).get("attempts", 0),
                "wrong_count": item["wrong_count"],
            })

    strategy = "bkt_adaptive"
    if len(picked) < limit:
        # 薄弱知识点的题不够，用题库里其余没做过的题补齐。
        # 不补的话请求 20 道只回 3 道，前端还得自己再发一次请求。
        fill = _fill_remaining(db, user_id, bank_id, limit - len(picked), seen)
        for q in fill:
            picked.append({
                "question": q,
                "kp_id": None,
                "reason": "薄弱知识点的题目不足，用未做过的题补齐覆盖面",
                "weight": None,
                "attempts": stats.get(q.id, {}).get("attempts", 0),
                "wrong_count": 0,
            })
        if fill:
            strategy = "bkt_adaptive_with_fill"

    return {
        "bank_id": bank_id,
        "strategy": strategy,
        "requested": limit,
        "returned": len(picked),
        "targets": [
            {
                "kp_id": kp_id,
                "name": names.get(kp_id, f"知识点 {kp_id}"),
                "p_known": round(p_of(kp_id), 4),
                "level": bkt.level(p_of(kp_id)),
                "need": round(bkt.need(p_of(kp_id)), 4),
                "question_count": kp_question_count.get(kp_id, 0),
                "attempts": (mastery[kp_id].attempts or 0) if kp_id in mastery else 0,
            }
            for kp_id in targets
        ],
        "picked": picked,
    }


def _fallback_no_kp(db: Session, user_id: int, bank_id: int, limit: int) -> dict:
    """题库里一道题都没标注知识点时的降级策略。

    这时"认知诊断"无从谈起（不知道题目考什么），但用户点进来总得能做上题。
    降级成"没做过的题优先"，同时在 `strategy` 里说清楚原因，
    前端据此提示"这个题库还没做知识点标注，去题库页跑一次自动标注"。
    """
    filled = _fill_remaining(db, user_id, bank_id, limit, set())
    return {
        "bank_id": bank_id,
        "strategy": "no_kp_fallback",
        "requested": limit,
        "returned": len(filled),
        "targets": [],
        "message": (
            "这个题库还没有题目标注知识点，无法做认知诊断。"
            "已按「没做过的题优先」出题；跑一次自动标注后即可按薄弱知识点出题。"
        ),
        "picked": [
            {
                "question": q,
                "kp_id": None,
                "reason": "题库未标注知识点，按未做过优先",
                "weight": None,
                "attempts": 0,
                "wrong_count": 0,
            }
            for q in filled
        ],
    }