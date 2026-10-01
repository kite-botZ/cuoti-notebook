"""Agent 工具定义与执行。

每个工具包含：
  - schema：给 LLM 看的 OpenAI 兼容描述
  - executor：真正的 Python 执行函数

所有 executor 都接收 ToolContext，里面带 db session 和 user_id，
保证每个工具都只在当前用户自己的数据里操作。
"""

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Question, QuestionBank, QuestionUserState


@dataclass
class ToolContext:
    """工具执行上下文。"""
    db: Session
    user_id: int


# ============================================================
# 工具 1：搜索错题
# ============================================================

def _search_wrong_questions(args: dict, ctx: ToolContext) -> dict:
    """
    搜索当前用户答错过的题目。
    - keyword：题目包含的关键词，为空则返回全部错题
    - limit：最多返回几道
    """
    keyword = (args.get("keyword") or "").strip()
    try:
        limit = int(args.get("limit") or 5)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 20))

    q = (
        ctx.db.query(Question, QuestionUserState)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .join(QuestionUserState, QuestionUserState.question_id == Question.id)
        .filter(
            QuestionBank.user_id == ctx.user_id,
            QuestionUserState.user_id == ctx.user_id,
            QuestionUserState.wrong_count > 0,
            Question.is_archived.is_(False),
        )
    )

    if keyword:
        q = q.filter(Question.stem.like(f"%{keyword}%"))

    rows = q.order_by(QuestionUserState.wrong_count.desc()).limit(limit).all()

    return {
        "count": len(rows),
        "questions": [
            {
                "id": q.id,
                "stem": (q.stem or "")[:150],
                "question_type": q.question_type,
                "wrong_count": s.wrong_count,
            }
            for q, s in rows
        ],
    }


# ============================================================
# 工具 2：批改计算题 / 简答题 / 填空题
# ============================================================

def _normalize_answer(s: str) -> str:
    """去掉空格和标点，转小写，用于宽松匹配。"""
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[，。！？；：、,.!?;:'\"“”‘’（）()\[\]【】]+", "", s)
    return s


def _grade_calculation(args: dict, ctx: ToolContext) -> dict:
    """
    对一道计算题/简答题/填空题的作答进行批改。
    - question_id：题目 ID
    - user_answer：用户给出的答案
    """
    try:
        question_id = int(args.get("question_id") or 0)
    except (TypeError, ValueError):
        question_id = 0

    user_answer = str(args.get("user_answer") or "").strip()

    if not question_id:
        return {"error": "缺少 question_id"}
    if not user_answer:
        return {"error": "用户答案为空"}

    question = (
        ctx.db.query(Question)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(
            Question.id == question_id,
            QuestionBank.user_id == ctx.user_id,
            Question.is_archived.is_(False),
        )
        .first()
    )

    if not question:
        return {"error": "题目不存在或无权访问"}

    if question.question_type not in ("calc", "short", "blank"):
        return {"error": f"题型 {question.question_type} 不支持批改"}

    is_correct = _normalize_answer(user_answer) == _normalize_answer(str(question.correct_answer))

    return {
        "is_correct": is_correct,
        "correct_answer": question.correct_answer,
        "user_answer": user_answer,
        "explanation": question.explanation or "",
    }


# ============================================================
# 工具 schema（给 LLM 看）
# ============================================================

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_wrong_questions",
            "description": (
                "搜索当前用户答错过的题目。"
                "当用户想查找错题、复习某类题目、问'我错过哪些题'时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词（题目包含的文字），不填则返回全部错题",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回几道题，默认 5，最多 20",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grade_calculation",
            "description": (
                "对一道计算题/简答题/填空题的作答进行批改。"
                "当用户说'我算的答案是 X，对吗'或给出自己的解答时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question_id": {
                        "type": "integer",
                        "description": "题目 ID（当前对话正在讨论的题目）",
                    },
                    "user_answer": {
                        "type": "string",
                        "description": "用户给出的答案",
                    },
                },
                "required": ["question_id", "user_answer"],
            },
        },
    },
]


# ============================================================
# 执行入口
# ============================================================

TOOLS_REGISTRY = {
    "search_wrong_questions": _search_wrong_questions,
    "grade_calculation": _grade_calculation,
}


def execute_tool(name: str, args: dict, ctx: ToolContext) -> dict:
    """执行一个工具，异常统一转成 {"error": ...}。"""
    fn = TOOLS_REGISTRY.get(name)
    if not fn:
        return {"error": f"未知工具：{name}"}
    try:
        return fn(args, ctx)
    except Exception as e:
        return {"error": f"工具执行失败：{e}"}