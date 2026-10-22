"""题库 / 题目 / 答题 / 状态 / 进度 相关接口。"""

import os
import re
import time

import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.cache import QLIST_TTL, cache
from app.db import get_db
from app.mastery import attach_kp_names, record_attempt
from app.models import AnswerAttempt, Question, QuestionBank, QuestionUserState
from app.security import ALGORITHM, SECRET_KEY

load_dotenv()

router = APIRouter(prefix="/api", tags=["question-banks"])

LETTERS = "ABCDEFGH"
VALID_TYPES = {"single", "multiple", "judge", "blank", "short", "calc"}


# ============================================================
# 请求体
# ============================================================

class BankCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    subject: str = Field(default="综合", min_length=1, max_length=50)
    description: str = Field(default="", max_length=255)


class QuestionCreate(BaseModel):
    stem: str = Field(min_length=1)
    question_type: str = Field(default="single")
    options: list[str] = Field(default_factory=list)
    correct_answer: str = Field(min_length=1)
    explanation: str = ""


class QuestionUpdate(BaseModel):
    stem: str | None = None
    question_type: str | None = None
    options: list[str] | None = None
    correct_answer: str | None = None
    explanation: str | None = None


class AnswerCreate(BaseModel):
    selected_answer: str = ""


class NoteBody(BaseModel):
    note: str = ""


class BatchCutBody(BaseModel):
    question_ids: list[int] = Field(min_length=1, max_length=500)
    is_cut: bool = True


# ============================================================
# 认证
# ============================================================

security = HTTPBearer(auto_error=False)


def current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> int:
    if not credentials:
        raise HTTPException(status_code=401, detail="请先登录")
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["id"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")


# ============================================================
# 辅助
# ============================================================

def bank_for_user(bank_id: int, user_id: int, db: Session) -> QuestionBank:
    bank = (
        db.query(QuestionBank)
        .filter(QuestionBank.id == bank_id, QuestionBank.user_id == user_id)
        .first()
    )
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")
    return bank


def ensure_question_owned(question_id: int, user_id: int, db: Session) -> Question:
    question = (
        db.query(Question)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(
            Question.id == question_id,
            QuestionBank.user_id == user_id,
            Question.is_archived.is_(False),
        )
        .first()
    )
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")
    return question


def get_or_create_state(user_id: int, question_id: int, db: Session) -> QuestionUserState:
    state = (
        db.query(QuestionUserState)
        .filter(
            QuestionUserState.user_id == user_id,
            QuestionUserState.question_id == question_id,
        )
        .first()
    )
    if not state:
        state = QuestionUserState(user_id=user_id, question_id=question_id)
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def question_payload(question: Question) -> dict:
    return {
        "id": question.id,
        "bank_id": question.bank_id,
        "stem": question.stem,
        "question_type": question.question_type,
        "options": question.options,
        "created_at": question.created_at,
    }


def question_payload_with_state(
    question: Question,
    state: QuestionUserState | None,
    include_answer: bool = False,
) -> dict:
    payload = {
        "id": question.id,
        "bank_id": question.bank_id,
        "stem": question.stem,
        "question_type": question.question_type,
        "options": question.options,
        "created_at": question.created_at,
        "is_favorite": bool(state.is_favorite) if state else False,
        "is_cut": bool(state.is_cut) if state else False,
        "note": state.note if state else "",
        "wrong_count": state.wrong_count if state else 0,
    }
    if include_answer:
        payload["correct_answer"] = question.correct_answer
        payload["explanation"] = question.explanation
    return payload


def state_fields(state: QuestionUserState | None) -> dict:
    """用户维度的状态字段。

    这部分**故意不缓存**：收藏/斩题/笔记/错题数是高频写、低延迟要求的个人数据，
    缓存它既省不了多少（本来就是按主键批量查）、又容易读到脏数据。
    缓存只放「题目内容」这种写少读多的数据。
    """
    return {
        "is_favorite": bool(state.is_favorite) if state else False,
        "is_cut": bool(state.is_cut) if state else False,
        "note": state.note if state else "",
        "wrong_count": state.wrong_count if state else 0,
    }


def _content_item(question: Question) -> dict:
    """题目内容快照（可缓存的部分）。"""
    return {
        "id": question.id,
        "bank_id": question.bank_id,
        "stem": question.stem,
        "question_type": question.question_type,
        "options": question.options,
        "created_at": question.created_at,
    }


# 题干里带 Markdown 图片的题（`![alt](url)`）。
#
# 前端 Bank.vue / Practice.vue 里用正则 /!\[[^\]]*\]\([^)]+\)/ 判断"看图题"，
# SQL 这边只做得到一个近似：LIKE 的 % 不区分"零个还是多个字符"，
# 所以 `![]()`（alt 和 url 都为空）在 SQL 会被算成看图题、在 JS 不会。
# 真实数据里不存在这种题干，这里接受这点差异，换来的是不用把两万条题干读进内存。
_IMAGE_STEM_LIKE = "%![%](%)%"


# 一次最多能按 id 白名单取多少题。
#
# 这个上限是给"恢复练习进度"和"随机练习"用的：前端把一批 id 丢过来换题目正文。
# 设上限是因为 ids 会被拼进 SQL 的 IN (...)，不设上限等于允许任意长的 IN 列表，
# 也让分页失去意义。100 和 page_size 的上限对齐。
MAX_IDS_FILTER = 100


def _parse_ids(raw: str | None) -> list[int]:
    """把 `ids=1,2,3` 解析成整数列表。

    非法输入直接 422，而不是静默忽略：如果前端传的 id 格式不对，
    "安静地返回全部题目"会让用户以为筛选生效了，排查起来很痛苦。
    """
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) > MAX_IDS_FILTER:
        raise HTTPException(
            status_code=422,
            detail=f"一次最多按 id 取 {MAX_IDS_FILTER} 道题，当前 {len(parts)} 道",
        )
    ids: list[int] = []
    for p in parts:
        try:
            ids.append(int(p))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"ids 里出现了非法的 id：{p}")
    return ids


def _like_pattern(text: str) -> str:
    r"""把用户输入变成 LIKE 模式，并转义 `%` / `_` 两个通配符。

    不转义的话搜「50%」会变成「50 后面跟任意字符」，搜出一堆无关的题。
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def validate_question(
    question_type: str,
    options: list[str],
    correct_answer: str,
) -> tuple[list[str], str]:
    if question_type not in VALID_TYPES:
        raise HTTPException(status_code=422, detail=f"不支持的题型：{question_type}")

    if question_type == "judge":
        options = ["正确", "错误"]
        ans = correct_answer.strip().upper()
        if ans not in ("A", "B"):
            raise HTTPException(status_code=422, detail="判断题答案必须是 A 或 B")
        return options, ans

    if question_type == "single":
        if len(options) < 2:
            raise HTTPException(status_code=422, detail="单选题至少需要 2 个选项")
        if any(not o.strip() for o in options):
            raise HTTPException(status_code=422, detail="选项不能为空")
        ans = correct_answer.strip().upper()
        if len(ans) != 1 or ans not in LETTERS[:len(options)]:
            raise HTTPException(
                status_code=422,
                detail=f"正确答案必须是 A~{LETTERS[len(options) - 1]} 中的一个",
            )
        return options, ans

    if question_type == "multiple":
        if len(options) < 2:
            raise HTTPException(status_code=422, detail="多选题至少需要 2 个选项")
        if any(not o.strip() for o in options):
            raise HTTPException(status_code=422, detail="选项不能为空")
        ans = correct_answer.strip().upper()
        ans = "".join(sorted(set(ans)))
        if len(ans) < 2:
            raise HTTPException(status_code=422, detail="多选题答案至少 2 个字母")
        for ch in ans:
            if ch not in LETTERS[:len(options)]:
                raise HTTPException(status_code=422, detail=f"答案含无效选项：{ch}")
        return options, ans

    if question_type == "blank":
        ans = correct_answer.strip()
        if not ans:
            raise HTTPException(status_code=422, detail="填空题答案不能为空")
        return [], ans

    if question_type in ("short", "calc"):
        ans = correct_answer.strip()
        if not ans:
            raise HTTPException(status_code=422, detail="答案不能为空")
        return [], ans

    raise HTTPException(status_code=422, detail="未知的题型")


# ============================================================
# 题库
# ============================================================

@router.get("/banks")
def list_banks(user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    rows = (
        db.query(QuestionBank, func.count(Question.id).label("question_count"))
        .outerjoin(
            Question,
            (Question.bank_id == QuestionBank.id) & (Question.is_archived.is_(False)),
        )
        .filter(QuestionBank.user_id == user_id)
        .group_by(QuestionBank.id)
        .order_by(QuestionBank.created_at.desc())
        .all()
    )
    return [
        {
            "id": bank.id,
            "name": bank.name,
            "subject": bank.subject,
            "description": bank.description,
            "question_count": count,
        }
        for bank, count in rows
    ]


@router.post("/banks", status_code=201)
def create_bank(
    body: BankCreate,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    bank = QuestionBank(user_id=user_id, **body.model_dump())
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return {
        "id": bank.id,
        "name": bank.name,
        "subject": bank.subject,
        "description": bank.description,
        "question_count": 0,
    }


@router.delete("/banks/{bank_id}")
def delete_bank(
    bank_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    bank = bank_for_user(bank_id, user_id, db)
    db.delete(bank)
    db.commit()
    # 缓存一致性：题库没了，它下面的题目缓存也要一起失效
    cache.bump_bank_version(bank_id)
    return {"message": "题库已删除"}


# ============================================================
# 题目
# ============================================================

def states_for(user_id: int, question_ids: list[int], db: Session) -> dict[int, QuestionUserState]:
    """按当前页的 id 批量取用户状态，避免逐题查询的 N+1。"""
    if not question_ids:
        return {}
    rows = (
        db.query(QuestionUserState)
        .filter(
            QuestionUserState.user_id == user_id,
            QuestionUserState.question_id.in_(question_ids),
        )
        .all()
    )
    return {s.question_id: s for s in rows}


@router.get("/banks/{bank_id}/questions")
def list_questions(
    bank_id: int,
    response: Response,
    filter_type: str | None = None,
    question_type: str | None = None,
    q: str | None = None,
    ids: str | None = None,
    has_image: bool | None = None,
    page: int | None = None,
    page_size: int = 50,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """题目列表。

    ## 分页

    - 传 `page`：返回第 `page` 页（`page_size` 默认 50、上限 100），
      响应头带 `X-Total-Count` / `X-Has-More`，前端据此做「加载更多」；
    - 不传 `page`：保持 v1 行为返回全量（老调用方兼容用）。

    ## 关键词搜索

    传 `q` 会在**服务端**按题干或笔记模糊匹配（`%` / `_` 已转义）。
    分页之后前端手里只有一个页的题，再做客户端过滤就只能搜到当前页，
    这是错的——所以搜索必须回源。

    搜索请求**不走缓存**：查询词是用户临时的，缓存收益低、key 还容易被刷爆。

    v1 是一次性 `order_by(Question.id.desc()).all()`：题库里有两万道题时，
    ORM 要把两万行实例化、再序列化成几 MB JSON 一次性吐出去。

    ## 按 id 白名单 / 看图题过滤

    - `ids=1,2,3`（最多 100 个）：只取这几道题。练习页恢复进度、
      "我勾选的题"、随机练习的分批取题都靠它——这些都是"手里已有 id，
      只缺题目正文"的场景，不需要把整库拉下来再本地筛。
    - `has_image=true|false`：只看 / 排除题干带 Markdown 图片的题。
      判定口径和 `/question-stats` 里的 `by_type.image` 完全一致
      （同一个 `_IMAGE_STEM_LIKE`），否则列表和计数会对不上。

    这两种过滤都**不走缓存**：id 列表是随机的长尾组合，进缓存只会被撑爆；
    和 `filter_type` 一样，宁可直接查库。

    ## 缓存一致性

    只缓存「题目内容」，key 里带题库版本号：

        cuoti:qlist:{bank_id}:{version}:{question_type}:{page}:{page_size}

    题目新增/修改/删除/批量导入后 `INCR cuoti:ver:bank:{bank_id}`，
    版本号一变，该题库所有旧 key 立刻失效（旧 key 靠 TTL 回收）。
    这样做的好处是不需要 `KEYS`/`SCAN` 批量删除——Redis 是单线程的，
    大 key 空间下 `KEYS` 会阻塞其它请求。

    用户状态（收藏/斩题/笔记/错题数）**不缓存**，按当前页 id 批量查库。
    这类数据写频率极高（每次答题、每次收藏都会变），缓存它省不了多少，
    却要额外保证一致性，不划算。
    """
    bank_for_user(bank_id, user_id, db)

    page_size = max(1, min(int(page_size or 50), 100))
    paginated = page is not None
    if paginated and page < 1:
        raise HTTPException(status_code=422, detail="page 必须 >= 1")

    id_list = _parse_ids(ids)

    include_answer = (filter_type == "cut")
    state_filtered = filter_type in ("wrong", "favorite", "cut", "note")

    # 只有「分页 + 不按用户状态过滤 + 无关键词 + 无 id 白名单 + 无图片过滤」
    # 这一种请求才进缓存。
    #
    # 为什么不缓存全量请求：不传 page 时一个题库两万道题，
    # 序列化出来是 8MB 的 JSON。把它塞进 Redis 有两个坏处——
    # 一是单个 key 8MB（Redis 单线程，操作大 key 会阻塞别的请求），
    # 二是「构造这个 value」的成本和直接查库差不多，缓存没省下什么。
    # 这类请求是 v1 的遗留调用方式，本身就该被分页取代，所以不回源缓存。
    #
    # 有关键词搜索时也不进缓存：查询词是用户临时输入的，几乎不会重复命中，
    # 缓存只会被各种长尾 q 撑大。
    keyword = (q or "").strip()
    use_cache = (
        paginated
        and not state_filtered
        and not keyword
        and not id_list
        and has_image is None
    )

    if use_cache:
        # ---------- 走缓存：题目内容 + 版本号 ----------
        version = cache.bank_version(bank_id)
        content_key = (
            f"cuoti:qlist:{bank_id}:{version}:{question_type or '-'}:{page}:{page_size}"
        )
        content = cache.get_json(content_key)
        if content is None:
            query = db.query(Question).filter(
                Question.bank_id == bank_id, Question.is_archived.is_(False)
            )
            if question_type:
                query = query.filter(Question.question_type == question_type)
            query = (
                query.order_by(Question.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            content = [_content_item(row) for row in query.all()]
            cache.set_json(content_key, content, QLIST_TTL)

        total_key = f"cuoti:qcount:{bank_id}:{version}:{question_type or '-'}"
        total = cache.get_json(total_key)
        if total is None:
            count_query = db.query(func.count(Question.id)).filter(
                Question.bank_id == bank_id, Question.is_archived.is_(False)
            )
            if question_type:
                count_query = count_query.filter(Question.question_type == question_type)
            total = int(count_query.scalar() or 0)
            cache.set_json(total_key, total, QLIST_TTL)

        states = states_for(user_id, [c["id"] for c in content], db)
        items = [
            {**c, **state_fields(states.get(c["id"]))}
            for c in content
        ]
    else:
        # ---------- 回源：全量兼容路径，或按用户状态过滤（必须联表）----------
        query = (
            db.query(Question, QuestionUserState)
            .outerjoin(
                QuestionUserState,
                (QuestionUserState.question_id == Question.id)
                & (QuestionUserState.user_id == user_id),
            )
            .filter(Question.bank_id == bank_id, Question.is_archived.is_(False))
        )

        if filter_type == "wrong":
            query = query.filter(QuestionUserState.wrong_count > 0)
        elif filter_type == "favorite":
            query = query.filter(QuestionUserState.is_favorite.is_(True))
        elif filter_type == "cut":
            query = query.filter(QuestionUserState.is_cut.is_(True))
        elif filter_type == "note":
            query = query.filter(QuestionUserState.note != "")

        if question_type:
            query = query.filter(Question.question_type == question_type)

        # 按 id 白名单取题。仍然要带上 bank_id 和 user_id 的归属校验
        # （上面的 bank_for_user 已经挡了别人的题库，这里再挡一次"不属于本题库的 id"，
        # 否则传别家题库的 id 就能跨库读题）。
        if id_list:
            query = query.filter(Question.id.in_(id_list))

        if has_image is not None:
            if has_image:
                query = query.filter(Question.stem.like(_IMAGE_STEM_LIKE))
            else:
                query = query.filter(~Question.stem.like(_IMAGE_STEM_LIKE))

        if keyword:
            # 题干或笔记命中即可。笔记在 QuestionUserState 上，这里已经 outer join 过，
            # 所以一条 SQL 就能同时搜两处。
            pattern = _like_pattern(keyword)
            query = query.filter(
                or_(
                    Question.stem.like(pattern, escape="\\"),
                    QuestionUserState.note.like(pattern, escape="\\"),
                )
            )

        query = query.order_by(Question.id.desc())

        if paginated:
            total = int(
                query.with_entities(func.count(Question.id)).order_by(None).scalar() or 0
            )
            query = query.offset((page - 1) * page_size).limit(page_size)

        rows = query.all()
        items = [question_payload_with_state(q, s, include_answer) for q, s in rows]
        if not paginated:
            total = len(items)

    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page if paginated else 1)
    response.headers["X-Page-Size"] = str(page_size if paginated else total)
    response.headers["X-Has-More"] = str(
        bool(paginated and page * page_size < total)
    ).lower()
    return items


@router.get("/banks/{bank_id}/question-stats")
def question_stats(
    bank_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """题库的各种计数，给分页后的题目列表用。

    分页之后前端手里只有一个页的题目，算不出「我的错题有几道」这类数字，
    所以计数必须由服务端给。

    刻意**用聚合查询一次算完**，而不是让前端对每个筛选条件各发一个
    `page_size=1` 的请求去读 `X-Total-Count` 响应头——那样一个页面要发十来个
    请求，每个都得走一遍鉴权和连接池。

    返回字段和前端 Bank.vue 里的几个 computed 一一对应：
    `total` / `normal` / `wrong` / `favorite` / `cut` / `note` / `by_type`。
    """
    bank_for_user(bank_id, user_id, db)

    # is_cut / wrong_count 可能整行是 NULL（这个用户还没碰过这道题），
    # 所以统一 coalesce 之后再比较；`is_cut.isnot(True)` 是空安全的
    # （SQL 里 `NULL IS NOT TRUE` 为真），不能写成 `!= True`，否则
    # 没碰过的题会被判成"已斩题"。
    not_cut = QuestionUserState.is_cut.isnot(True)

    def _joined():
        return (
            db.query(Question, QuestionUserState)
            .outerjoin(
                QuestionUserState,
                (QuestionUserState.question_id == Question.id)
                & (QuestionUserState.user_id == user_id),
            )
            .filter(Question.bank_id == bank_id, Question.is_archived.is_(False))
        )

    row = _joined().with_entities(
        func.count(Question.id),
        func.sum(case((QuestionUserState.is_cut.is_(True), 1), else_=0)),
        func.sum(case((not_cut, 1), else_=0)),
        func.sum(
            case(
                (not_cut & (func.coalesce(QuestionUserState.wrong_count, 0) > 0), 1),
                else_=0,
            )
        ),
        func.sum(
            case((not_cut & QuestionUserState.is_favorite.is_(True), 1), else_=0)
        ),
        func.sum(
            case((func.coalesce(QuestionUserState.note, "") != "", 1), else_=0)
        ),
    ).one()
    total, cut, normal, wrong, favorite, note = (int(v or 0) for v in row)

    # 分题型计数。有图的题单独算一类、不再计入原题型——口径和前端 typeList
    # 一致（看图题占一个格子，原题型格子里不重复算它）。
    type_expr = case(
        (Question.stem.like(_IMAGE_STEM_LIKE), "image"),
        else_=Question.question_type,
    )
    type_rows = (
        _joined()
        .with_entities(type_expr, func.count(Question.id))
        .filter(not_cut)
        .group_by(type_expr)
        .all()
    )

    by_type = {t: 0 for t in VALID_TYPES}
    by_type["image"] = 0
    for name, count in type_rows:
        by_type[str(name)] = int(count or 0)

    return {
        "bank_id": bank_id,
        "total": total,
        "normal": normal,
        "cut": cut,
        "wrong": wrong,
        "favorite": favorite,
        "note": note,
        "by_type": by_type,
    }


@router.get("/banks/{bank_id}/question-ids")
def question_ids(
    bank_id: int,
    filter_type: str | None = None,
    question_type: str | None = None,
    has_image: bool | None = None,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """题库里符合条件的题目 id，给「随机练习 / 打乱题序」用。

    ## 为什么不直接返回题目

    "随机练习"要的是**整库打乱**，而分页接口只能按固定顺序一页页给，
    在客户端打乱已经加载的那一页并不是真的随机。所以拆成两步：

    1. 先取 id（这里），数量级是每个 id 几个字节；
    2. 打乱 id 顺序，再按 `ids=` 分批取题目正文（一次最多 100 道）。

    两万道题时，第 1 步约 120KB、第 2 步每批约 15KB；
    而 v1 的做法是一次拉 8MB 的题目正文再在浏览器里 shuffle。

    ## 过滤口径必须和列表接口一致

    `filter_type` / `question_type` / `has_image` 的语义和
    `GET /banks/{bank_id}/questions` 完全相同（`filter_type` 支持
    wrong / favorite / cut / note）。如果不一致，会出现"打乱之后冒出没做错的题"
    这种问题——所以 `test_pagination_cache.py` 里有一条用例专门比对两边。

    ## 只有 id，没有题目内容

    这里**只查 id 列**（`db.query(Question.id)`），不构造 ORM 实例，
    也不走题目列表缓存——理由和列表接口一样，两万行的序列化成本全在正文上。
    """
    bank_for_user(bank_id, user_id, db)

    query = (
        db.query(Question.id)
        .outerjoin(
            QuestionUserState,
            (QuestionUserState.question_id == Question.id)
            & (QuestionUserState.user_id == user_id),
        )
        .filter(Question.bank_id == bank_id, Question.is_archived.is_(False))
    )

    if filter_type == "wrong":
        query = query.filter(QuestionUserState.wrong_count > 0)
    elif filter_type == "favorite":
        query = query.filter(QuestionUserState.is_favorite.is_(True))
    elif filter_type == "cut":
        query = query.filter(QuestionUserState.is_cut.is_(True))
    elif filter_type == "note":
        query = query.filter(QuestionUserState.note != "")

    if question_type:
        query = query.filter(Question.question_type == question_type)
    if has_image is not None:
        if has_image:
            query = query.filter(Question.stem.like(_IMAGE_STEM_LIKE))
        else:
            query = query.filter(~Question.stem.like(_IMAGE_STEM_LIKE))

    rows = query.order_by(Question.id.desc()).all()
    ids = [int(r[0]) for r in rows]
    return {"bank_id": bank_id, "total": len(ids), "ids": ids}


@router.post("/banks/{bank_id}/questions", status_code=201)
def create_question(
    bank_id: int,
    body: QuestionCreate,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    bank_for_user(bank_id, user_id, db)
    options, correct_answer = validate_question(
        body.question_type, body.options, body.correct_answer
    )
    question = Question(
        bank_id=bank_id,
        stem=body.stem.strip(),
        question_type=body.question_type,
        options=options,
        correct_answer=correct_answer,
        explanation=body.explanation,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    # 写后失效：版本号 +1，该题库的题目列表缓存key全部作废
    cache.bump_bank_version(bank_id)
    return question_payload(question)


@router.put("/questions/{question_id}")
def update_question(
    question_id: int,
    body: QuestionUpdate,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    question = ensure_question_owned(question_id, user_id, db)

    new_type = body.question_type if body.question_type is not None else question.question_type
    new_options = body.options if body.options is not None else list(question.options or [])
    new_answer = body.correct_answer if body.correct_answer is not None else question.correct_answer

    options, correct_answer = validate_question(new_type, new_options, new_answer)

    if body.stem is not None:
        if not body.stem.strip():
            raise HTTPException(status_code=422, detail="题干不能为空")
        question.stem = body.stem.strip()
    if body.explanation is not None:
        question.explanation = body.explanation

    question.question_type = new_type
    question.options = options
    question.correct_answer = correct_answer

    db.commit()
    db.refresh(question)
    cache.bump_bank_version(question.bank_id)
    return question_payload(question)


@router.delete("/questions/{question_id}")
def delete_question(
    question_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    question = ensure_question_owned(question_id, user_id, db)
    bank_id = question.bank_id
    db.delete(question)
    db.commit()
    cache.bump_bank_version(bank_id)
    return {"message": "题目已删除"}


# ============================================================
# 答题
# ============================================================

@router.post("/questions/{question_id}/answer")
def submit_answer(
    question_id: int,
    body: AnswerCreate,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    question = ensure_question_owned(question_id, user_id, db)

    user_ans = str(body.selected_answer).strip()

    # 除简答 / 计算外，其他题型不能空
    if question.question_type not in ("short", "calc") and not user_ans:
        raise HTTPException(status_code=422, detail="答案不能为空")

    correct_str = str(question.correct_answer or "")

    # 用户答案含图片（如上传了草稿）→ 无法自动判分，让用户自评
    user_has_image = "![" in user_ans

    need_self_check = False
    is_correct = False

    if user_has_image:
        need_self_check = True
    elif question.question_type == "multiple":
        correct_set = set(correct_str.upper())
        user_set = set(user_ans.upper())
        is_correct = (correct_set == user_set)
    elif question.question_type in ("short", "calc"):
        def normalize(s: str) -> str:
            s = s.strip().lower()
            s = re.sub(r"\s+", "", s)
            s = re.sub(r"[，。！？；：、,.!?;:'\"“”‘’（）()\[\]【】]+", "", s)
            return s
        is_correct = normalize(user_ans) == normalize(correct_str)
    else:
        is_correct = user_ans.upper() == correct_str.upper()

    # 写答题历史
    attempt = AnswerAttempt(
        user_id=user_id,
        question_id=question.id,
        selected_answer=user_ans or "(空)",
        is_correct=is_correct,
    )
    db.add(attempt)

    # 自评题不算错，其他答错才 +1
    if not is_correct and not need_self_check:
        state = get_or_create_state(user_id, question.id, db)
        state.wrong_count = (state.wrong_count or 0) + 1

    # 认知诊断：这次作答让相关知识点的掌握度变化多少。
    # 自评题也一样要更新——自评结果是用户自己给的判断，仍是关于"会不会"的证据；
    # 而且跳过它会让"上传了图片的解答"永远不影响诊断。
    mastery_changes = attach_kp_names(
        db,
        record_attempt(db, user_id, question, is_correct),
    )

    db.commit()

    return {
        "correct": is_correct,
        "need_self_check": need_self_check,
        "correct_answer": question.correct_answer,
        "explanation": question.explanation,
        "answered_at": int(time.time()),
        # 掌握度变化随判题结果一起返回：前端答完立刻能显示
        # "「TCP 拥塞控制」0.42 → 0.53"，诊断有没有真的在动，一眼可见
        "mastery_changes": mastery_changes,
    }


# ============================================================
# 状态
# ============================================================

@router.post("/questions/{question_id}/favorite")
def toggle_favorite(
    question_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    ensure_question_owned(question_id, user_id, db)
    state = get_or_create_state(user_id, question_id, db)
    state.is_favorite = not state.is_favorite
    db.commit()
    return {"question_id": question_id, "is_favorite": state.is_favorite}


@router.post("/questions/{question_id}/cut")
def toggle_cut(
    question_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    ensure_question_owned(question_id, user_id, db)
    state = get_or_create_state(user_id, question_id, db)
    state.is_cut = not state.is_cut
    db.commit()
    return {"question_id": question_id, "is_cut": state.is_cut}


@router.post("/banks/{bank_id}/questions/batch-cut")
def batch_cut(
    bank_id: int,
    body: BatchCutBody,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    bank_for_user(bank_id, user_id, db)
    questions = (
        db.query(Question)
        .filter(
            Question.id.in_(body.question_ids),
            Question.bank_id == bank_id,
            Question.is_archived.is_(False),
        )
        .all()
    )
    if not questions:
        raise HTTPException(status_code=404, detail="没有找到可操作的题目")

    # 批量取已有状态，一次查完；缺的批量补，最后只 commit 一次。
    # v1 是在循环里逐个 get_or_create_state——每次都可能单独 commit，
    # 500 道题最坏就是 500 次 SELECT + 500 次 INSERT + 几百次事务提交。
    ids = [q.id for q in questions]
    existing = states_for(user_id, ids, db)
    for qid in ids:
        state = existing.get(qid)
        if state is None:
            state = QuestionUserState(user_id=user_id, question_id=qid)
            db.add(state)
            existing[qid] = state
        state.is_cut = body.is_cut
    db.commit()
    # 只改了用户状态、没动题目内容，所以不用动题库版本号：
    # 列表接口的用户状态字段本来就不走缓存。
    action = "斩题" if body.is_cut else "恢复"
    return {"message": f"已{action} {len(questions)} 道题", "count": len(questions)}


@router.put("/questions/{question_id}/note")
def save_note(
    question_id: int,
    body: NoteBody,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    ensure_question_owned(question_id, user_id, db)
    state = get_or_create_state(user_id, question_id, db)
    state.note = body.note
    db.commit()
    return {"question_id": question_id, "note": state.note}


@router.get("/banks/{bank_id}/progress")
def bank_progress(
    bank_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    bank_for_user(bank_id, user_id, db)

    total = (
        db.query(func.count(Question.id))
        .filter(Question.bank_id == bank_id, Question.is_archived.is_(False))
        .scalar()
        or 0
    )
    correct = (
        db.query(func.count(AnswerAttempt.id))
        .join(Question, AnswerAttempt.question_id == Question.id)
        .filter(
            AnswerAttempt.user_id == user_id,
            Question.bank_id == bank_id,
            AnswerAttempt.is_correct.is_(True),
        )
        .scalar()
        or 0
    )
    attempts = (
        db.query(func.count(AnswerAttempt.id))
        .join(Question, AnswerAttempt.question_id == Question.id)
        .filter(AnswerAttempt.user_id == user_id, Question.bank_id == bank_id)
        .scalar()
        or 0
    )
    return {
        "question_count": total,
        "attempt_count": attempts,
        "correct_count": correct,
        "accuracy": round(correct / attempts, 4) if attempts else 0,
    }