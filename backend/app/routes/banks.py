"""题库 / 题目 / 答题 / 状态 / 进度 相关接口。"""

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
    return {"message": "题库已删除"}


# ============================================================
# 题目
# ============================================================

@router.get("/banks/{bank_id}/questions")
def list_questions(
    bank_id: int,
    filter_type: str | None = None,
    question_type: str | None = None,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    bank_for_user(bank_id, user_id, db)

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

    rows = query.order_by(Question.id.desc()).all()
    include_answer = (filter_type == "cut")

    return [
        question_payload_with_state(question, state, include_answer)
        for question, state in rows
    ]


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
    return question_payload(question)


@router.delete("/questions/{question_id}")
def delete_question(
    question_id: int,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    question = ensure_question_owned(question_id, user_id, db)
    db.delete(question)
    db.commit()
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

    db.commit()

    return {
        "correct": is_correct,
        "need_self_check": need_self_check,
        "correct_answer": question.correct_answer,
        "explanation": question.explanation,
        "answered_at": int(time.time()),
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
    for q in questions:
        state = get_or_create_state(user_id, q.id, db)
        state.is_cut = body.is_cut
    db.commit()
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