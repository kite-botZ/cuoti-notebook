"""题库 / 题目 / 答题 / 状态 / 进度 相关接口。

关键设计：
1. 题目列表不返回正确答案，只有提交答案的接口才返回。
2. 题库和题目都按 user_id 隔离，防止越权。
3. 答题历史 AnswerAttempt 只增不改；QuestionUserState 每个用户对每道题一条记录。
4. 支持 5 种题型：single / multiple / judge / blank / short。
5. 题干和选项支持 Markdown 图片语法 ![](url)，前端自行渲染。
"""

import os
import re
import time

import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AnswerAttempt, Question, QuestionBank, QuestionUserState

load_dotenv()

router = APIRouter(prefix="/api", tags=["question-banks"])

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-fallback-secret")
ALGORITHM = "HS256"

# 选项字母表（最多 8 个选项）
LETTERS = "ABCDEFGH"

# 支持的题型
VALID_TYPES = {"single", "multiple", "judge", "blank", "short"}


# ============================================================
# 请求体模型
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
    # 简答题可能为空，其他题型由业务层校验
    selected_answer: str = ""


class NoteBody(BaseModel):
    note: str = ""


class BatchCutBody(BaseModel):
    question_ids: list[int] = Field(min_length=1, max_length=500)
    is_cut: bool = True


# ============================================================
# 认证依赖
# ============================================================

security = HTTPBearer(auto_error=False)


def current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> int:
    """从 Authorization: Bearer <token> 里解析出 user_id。"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["id"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已失效，请重新登录",
        )


# ============================================================
# 辅助函数
# ============================================================

def bank_for_user(bank_id: int, user_id: int, db: Session) -> QuestionBank:
    """确认题库存在且属于当前用户，否则抛 404。"""
    bank = (
        db.query(QuestionBank)
        .filter(QuestionBank.id == bank_id, QuestionBank.user_id == user_id)
        .first()
    )
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")
    return bank


def ensure_question_owned(question_id: int, user_id: int, db: Session) -> Question:
    """确认题目属于当前用户的某个题库，否则抛 404。"""
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
    """获取用户对某题的状态，没有就创建默认的。"""
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
    """练习时返回的安全结构，不含正确答案。"""
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
    """
    题目信息 + 用户对它的状态。
    include_answer=True 时才返回正确答案和解析（用于斩题列表等查看场景）。
    """
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


def validate_question(
    question_type: str,
    options: list[str],
    correct_answer: str,
) -> tuple[list[str], str]:
    """
    校验题目结构，返回规范化后的 (options, correct_answer)。
    不合法时抛 422。
    """
    if question_type not in VALID_TYPES:
        raise HTTPException(status_code=422, detail=f"不支持的题型：{question_type}")

    # 判断题：强制两个固定选项
    if question_type == "judge":
        options = ["正确", "错误"]
        ans = correct_answer.strip().upper()
        if ans not in ("A", "B"):
            raise HTTPException(status_code=422, detail="判断题答案必须是 A 或 B")
        return options, ans

    # 单选题
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

    # 多选题：答案是多字母组合，去重排序
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

    # 填空题：无选项，答案为文本
    if question_type == "blank":
        ans = correct_answer.strip()
        if not ans:
            raise HTTPException(status_code=422, detail="填空题答案不能为空")
        return [], ans

    # 简答题：无选项，答案为参考答案
    if question_type == "short":
        ans = correct_answer.strip()
        if not ans:
            raise HTTPException(status_code=422, detail="简答题答案不能为空")
        return [], ans

    # 理论上不会走到这
    raise HTTPException(status_code=422, detail="未知的题型")


# ============================================================
# 题库接口
# ============================================================

@router.get("/banks")
def list_banks(user_id: int = Depends(current_user_id), db: Session = Depends(get_db)):
    """列出当前用户的所有题库，附带每库的题目数。"""
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


@router.post("/banks", status_code=status.HTTP_201_CREATED)
def create_bank(
    body: BankCreate,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """新建题库。"""
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
    """删除题库。外键 CASCADE 会一并删除题目、答题记录、状态。"""
    bank = bank_for_user(bank_id, user_id, db)
    db.delete(bank)
    db.commit()
    return {"message": "题库已删除"}


# ============================================================
# 题目接口
# ============================================================

@router.get("/banks/{bank_id}/questions")
def list_questions(
    bank_id: int,
    filter_type: str | None = None,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """
    列出题库里的题目。

    filter_type 可选值：
      - None（不传）：全部题目
      - wrong：做错过
      - favorite：已收藏
      - cut：已斩题（此时返回答案和解析）
      - note：有笔记
    """
    bank_for_user(bank_id, user_id, db)

    # 用 outerjoin，保证没有状态记录的题也能查到
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

    rows = query.order_by(Question.id.desc()).all()

    # 斩题列表是"已移出练习"的题，允许看答案
    include_answer = (filter_type == "cut")

    return [
        question_payload_with_state(question, state, include_answer)
        for question, state in rows
    ]


@router.post("/banks/{bank_id}/questions", status_code=status.HTTP_201_CREATED)
def create_question(
    bank_id: int,
    body: QuestionCreate,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """新建题目。"""
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
    return question_payload(question)


@router.put("/questions/{question_id}")
def update_question(
    question_id: int,
    body: QuestionUpdate,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """
    编辑题目。
    只更新请求里传了的字段，没传的保持原值。
    """
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
    return question_payload(question)


@router.delete("/questions/{question_id}")
def delete_question(
    question_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """删除题目。相关答题记录、状态会一并删除。"""
    question = ensure_question_owned(question_id, user_id, db)
    db.delete(question)
    db.commit()
    return {"message": "题目已删除"}


# ============================================================
# 答题接口
# ============================================================

@router.post("/questions/{question_id}/answer")
def submit_answer(
    question_id: int,
    body: AnswerCreate,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """
    提交答案并判分。
    - 单选 / 判断：selected_answer 传 "A" / "B"
    - 多选：selected_answer 传 "AB"
    - 填空：selected_answer 传文本
    - 简答：selected_answer 传文本
    """
    question = ensure_question_owned(question_id, user_id, db)

    user_ans = str(body.selected_answer).strip()

    # 除简答外，其他题型不能空
    if question.question_type != "short" and not user_ans:
        raise HTTPException(status_code=422, detail="答案不能为空")

    if question.question_type == "multiple":
        # 多选：拆成集合比较，顺序无关
        correct_set = set(str(question.correct_answer).upper())
        user_set = set(user_ans.upper())
        is_correct = (correct_set == user_set)
    elif question.question_type == "short":
        # 简答：去空格、去标点、转小写后比对
        def normalize(s: str) -> str:
            s = s.strip().lower()
            s = re.sub(r"\s+", "", s)
            s = re.sub(r"[，。！？；：、,.!?;:'\"“”‘’（）()\[\]【】]+", "", s)
            return s
        is_correct = normalize(user_ans) == normalize(str(question.correct_answer))
    else:
        # 单选 / 判断 / 填空：忽略大小写直接比
        is_correct = user_ans.upper() == str(question.correct_answer).upper()

    # 写答题历史
    attempt = AnswerAttempt(
        user_id=user_id,
        question_id=question.id,
        selected_answer=user_ans,
        is_correct=is_correct,
    )
    db.add(attempt)

    # 更新用户对题目的状态：答错时 wrong_count + 1
    state = get_or_create_state(user_id, question.id, db)
    if not is_correct:
        state.wrong_count = (state.wrong_count or 0) + 1

    db.commit()

    return {
        "correct": is_correct,
        "correct_answer": question.correct_answer,
        "explanation": question.explanation,
        "answered_at": int(time.time()),
    }


# ============================================================
# 题目状态接口
# ============================================================

@router.post("/questions/{question_id}/favorite")
def toggle_favorite(
    question_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """切换收藏状态。"""
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
    """切换斩题状态。"""
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
    """批量斩题或恢复。"""
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

    for q in questions:
        state = get_or_create_state(user_id, q.id, db)
        state.is_cut = body.is_cut

    db.commit()

    action = "斩题" if body.is_cut else "恢复"
    return {
        "message": f"已{action} {len(questions)} 道题",
        "count": len(questions),
    }


@router.put("/questions/{question_id}/note")
def save_note(
    question_id: int,
    body: NoteBody,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """保存笔记，整体覆盖。"""
    ensure_question_owned(question_id, user_id, db)
    state = get_or_create_state(user_id, question_id, db)
    state.note = body.note
    db.commit()
    return {"question_id": question_id, "note": state.note}


# ============================================================
# 进度接口
# ============================================================

@router.get("/banks/{bank_id}/progress")
def bank_progress(
    bank_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """题库统计：题目数、答题次数、正确数、正确率。"""
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