from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, func, \
    UniqueConstraint

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)  # 演示用明文；生产要哈希
    created_at = Column(DateTime, server_default=func.now())


class QuestionBank(Base):
    __tablename__ = "question_banks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    subject = Column(String(50), nullable=False, default="综合")
    description = Column(String(255), nullable=False, default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Question(Base):
    __tablename__ = "questions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bank_id = Column(BigInteger, ForeignKey("question_banks.id", ondelete="CASCADE"), nullable=False, index=True)
    stem = Column(Text, nullable=False)
    question_type = Column(String(20), nullable=False, default="single")
    options = Column(JSON, nullable=False)
    correct_answer = Column(String(50), nullable=False)
    explanation = Column(Text, nullable=False, default="")
    is_archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AnswerAttempt(Base):
    __tablename__ = "answer_attempts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(BigInteger, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    selected_answer = Column(Integer, nullable=False)
    is_correct = Column(Boolean, nullable=False)
    answered_at = Column(DateTime, server_default=func.now(), nullable=False)

class QuestionUserState(Base):
    __tablename__ = "question_user_states"

    # 联合唯一约束：同一个用户 + 同一道题，只能有一条记录
    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="uq_user_question"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(BigInteger, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)

    is_favorite = Column(Boolean, nullable=False, default=False)   # 是否收藏
    is_cut = Column(Boolean, nullable=False, default=False)        # 是否斩题（不再出现在练习中）
    note = Column(Text, nullable=False, default="")                # 本题笔记
    wrong_count = Column(Integer, nullable=False, default=0)       # 累计答错次数

    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class PracticeSession(Base):
    """用户在某题库某模式下的练习进度。

    每个 (user_id, bank_id, source) 组合唯一。
    """
    __tablename__ = "practice_sessions"

    __table_args__ = (
        UniqueConstraint("user_id", "bank_id", "source", name="uq_practice_session"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    bank_id = Column(BigInteger, ForeignKey("question_banks.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String(20), nullable=False, index=True)

    question_ids = Column(JSON, nullable=False)
    answers = Column(JSON, nullable=False, default=dict)
    current_index = Column(Integer, nullable=False, default=0)

    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class UserSettings(Base):
    """用户个性化设置。

    单独建表而不在 users 上加字段，是为了以后加新设置时不用 ALTER TABLE。
    """
    __tablename__ = "user_settings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    daily_goal = Column(Integer, nullable=False, default=20)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


