from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, ForeignKey,
    Index, Integer, JSON, String, Text, UniqueConstraint, func,
)
from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)  # 演示用明文；生产要哈希
    created_at = Column(DateTime, server_default=func.now())


class QuestionBank(Base):
    __tablename__ = "question_banks"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    subject = Column(String(50), nullable=False, default="综合")
    description = Column(String(255), nullable=False, default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Question(Base):
    __tablename__ = "questions"

    # 题目列表接口固定按 (bank_id, is_archived) 过滤、按 id 倒序分页，
    # 单列索引 bank_id 之后还要回表过滤 is_archived 再排序；
    # 换成覆盖这三列的联合索引，排序和过滤都能在索引里做完。
    __table_args__ = (
        Index("ix_questions_bank_active_id", "bank_id", "is_archived", "id"),
    )

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
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

    # 「查某道题的答题历史 / 统计某题库正确率」都是按 (user_id, question_id) 组合查
    __table_args__ = (
        Index("ix_attempts_user_question", "user_id", "question_id"),
    )

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(BigInteger, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True)
    # 修复：这里原本声明成 Integer，但写库时传的是 body.selected_answer（字符串，
    # 多选题是 "AB" 这种）。SQLite 是弱类型所以测试全绿，MySQL 严格模式下
    # 会直接报 1366 Incorrect integer value —— 属于被测试环境掩盖的线上必崩缺陷。
    selected_answer = Column(String(255), nullable=False)
    is_correct = Column(Boolean, nullable=False)
    answered_at = Column(DateTime, server_default=func.now(), nullable=False)

class QuestionUserState(Base):
    __tablename__ = "question_user_states"

    # 联合唯一约束：同一个用户 + 同一道题，只能有一条记录
    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="uq_user_question"),
        # 错题检索固定按 user_id + wrong_count>0 过滤、再按 wrong_count 排序
        Index("ix_qus_user_wrong", "user_id", "wrong_count"),
    )

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
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

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
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

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    daily_goal = Column(Integer, nullable=False, default=20)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ============================================================
# 知识点相关（认知诊断的基础）
# ============================================================

class KnowledgePoint(Base):
    """知识点——学科知识体系里的一个节点。

    ## 为什么必须全局共享，而不是挂在用户下面

    「错题认知诊断」诊断的对象是**知识点**，不是题目。
    如果知识点按用户隔离，同一个「二次函数顶点式」会变成几十条互不相干的记录，
    学生之间没法比较、诊断结果也没法汇总。所以知识点是学科层面的公共分类，
    和题库的归属（user_id）是两回事。

    ## parent_id

    支持层级（「函数」→「二次函数」→「顶点式」）。前端可以按树展示，
    诊断时也能把子知识点的掌握度向上汇总。

    ## 唯一性

    `(subject, name)` 唯一：同一学科里不允许出现两个同名知识点。
    没有把 parent_id 放进唯一约束，是因为 MySQL 里 `NULL != NULL`，
    唯一约束对「顶级节点」根本不生效，容易埋坑。
    """
    __tablename__ = "knowledge_points"

    __table_args__ = (
        UniqueConstraint("subject", "name", name="uq_kp_subject_name"),
    )

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    subject = Column(String(50), nullable=False, default="综合", index=True)
    parent_id = Column(
        BigInteger,
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    description = Column(String(255), nullable=False, default="")
    created_at = Column(DateTime, server_default=func.now())


class QuestionKnowledgePoint(Base):
    """题目 ↔ 知识点 的多对多关联。

    - `weight`：这道题对该知识点的考查权重（0~1）。一道题常常同时考好几个知识点，
      后面 BKT 更新掌握度时按 weight 分配这次作答的影响。
    - `source`：这条关联怎么来的——`manual` 人工标注 / `llm` 模型自动标注。
      论文里要用它统计「自动标注占比」，也方便人工复核时只挑 llm 的看。
    """
    __tablename__ = "question_knowledge_points"

    __table_args__ = (
        UniqueConstraint("question_id", "kp_id", name="uq_question_kp"),
        Index("ix_qkp_kp", "kp_id", "question_id"),
    )

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    question_id = Column(
        BigInteger,
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kp_id = Column(
        BigInteger,
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    weight = Column(Float, nullable=False, default=1.0)
    source = Column(String(20), nullable=False, default="manual")
    created_at = Column(DateTime, server_default=func.now())


