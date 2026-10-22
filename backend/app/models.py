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


class UserKpMastery(Base):
    """某个用户对某个知识点的掌握度——认知诊断的结论就存在这张表里。

    ## 为什么不是算出来就行，非要落库

    掌握度是**在线增量**更新的：每答一题，只把受影响的几个知识点推进一小步。
    如果每次都从 `answer_attempts` 全量重算，随着作答记录增长会越来越慢，
    而且重算必须把历史的作答顺序也复现出来（BKT 是非交换的，先错后对和先对后错
    结果不同），代价远大于增量更新。

    增量更新也意味着这张表是**可以被重放的**：诊断逻辑一旦改了参数或公式，
    清空这张表、按 `answer_attempts` 的时间顺序重放即可，不需要额外的手工修数据。

    ## p_known 的语义

    `p_known` 是 BKT 的隐状态后验：**这个知识点已掌握的概率**，恒在 [0.01, 0.99]。
    它不等于正确率，所以这里同时存 `attempts` / `correct`，前端两个都能展示，
    也方便核对"掌握度是不是被某一道题带偏了"。

    ## 为什么 (user_id, kp_id) 唯一，而不带 bank_id

    知识点是学科层面的公共分类（见 `KnowledgePoint` 的说明），同一个知识点
    可能被多个题库的题考到。掌握度跟着**人和知识点**走，不跟着题库走：
    学生在题库 A 练会了「二次函数顶点式」，在题库 B 里再做同类题时，
    初始掌握度就不该再从 0.30 重新开始。带 bank_id 会让同一份能力被拆成几份，
    诊断结果互相矛盾。
    """

    __tablename__ = "user_kp_mastery"

    __table_args__ = (
        UniqueConstraint("user_id", "kp_id", name="uq_user_kp_mastery"),
        # 自适应选题固定按 user_id 过滤、按 p_known 升序挑最弱的知识点，
        # 所以建联合索引；user_id 是它的最左前缀，不再单独建单列索引。
        Index("ix_mastery_user_p", "user_id", "p_known"),
    )

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id = Column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # kp_id 上不再 `index=True`：唯一约束 uq_user_kp_mastery 的最左前缀是 user_id，
    # 但 MySQL 会为它建一个 (user_id, kp_id) 索引，按 kp_id 单查虽然用不上前缀，
    # 诊断里也没有"按 kp_id 反查所有用户"的场景，多一个单列索引只是多一份写开销。
    kp_id = Column(
        BigInteger, ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
    )

    p_known = Column(Float, nullable=False, default=0.30)
    attempts = Column(Integer, nullable=False, default=0)   # 影响过这个知识点的作答次数
    correct = Column(Integer, nullable=False, default=0)

    # 最近一次作答时间。自适应选题用它避免"刚做过又推给你"，
    # 也留着以后做遗忘衰减（decay）用——现在没做，别假装做了。
    last_answered_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ============================================================
# 知识库文档（RAG 的语料来源）
# ============================================================

class KnowledgeDocument(Base):
    """一本教材 / 一份讲义。

    ## 为什么全局共享

    教材是学科的公共知识，不是某个用户的私有数据。全局共享意味着
    所有用户的检索都能命中同一份语料，知识库只会越用越全。

    ## status 的意义

    解析 + 切分 + 向量化是一条比较长的链路，中间任何一步都可能失败
    （扫描件抽不出字、模型服务没开）。把状态落库，前端就能显示
    「处理中 / 就绪 / 失败（原因）」，而不是让用户对着一个转圈的按钮干等。
    """
    __tablename__ = "knowledge_documents"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    subject = Column(String(50), nullable=False, default="综合", index=True)
    filename = Column(String(255), nullable=False, default="")
    file_type = Column(String(20), nullable=False, default="")

    char_count = Column(Integer, nullable=False, default=0)
    chunk_count = Column(Integer, nullable=False, default=0)
    # pending / ready / failed
    status = Column(String(20), nullable=False, default="pending", index=True)
    error = Column(Text, nullable=False, default="")
    # 哪一步失败的：load / clean / chunk / embed
    failed_stage = Column(String(20), nullable=False, default="")

    embed_model = Column(String(80), nullable=False, default="")
    uploaded_by = Column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, server_default=func.now())


class DocumentChunk(Base):
    """文档切出来的一个片段——检索的最小单位。

    ## 元数据比文本更重要

    纯向量相似度经常召回「字面像但知识点不相关」的段落。
    这里把 `kp_id` / `subject` / `chapter` 一起存下来，检索时可以先按元数据过滤
    再做向量比对，准确率会明显高于纯向量。论文里的对比实验就靠这几个字段。

    ## embedding 用 JSON 存

    小规模知识库（几千个 chunk）直接存在 MySQL 里、查出来在内存算余弦就够了，
    不需要引入专门的向量数据库。规模上千以后可以换 pgvector / Chroma，
    检索接口不用变。`embed_model` 要一起存：换模型后旧向量必须重建，
    否则不同模型的向量混在一起算相似度是没意义的。
    """
    __tablename__ = "document_chunks"

    __table_args__ = (
        Index("ix_chunk_doc_index", "doc_id", "chunk_index"),
        Index("ix_chunk_subject", "subject"),
        Index("ix_chunk_kp", "kp_id"),
    )

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    doc_id = Column(
        BigInteger,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index = Column(Integer, nullable=False, default=0)

    text = Column(Text, nullable=False)
    char_count = Column(Integer, nullable=False, default=0)

    subject = Column(String(50), nullable=False, default="综合")
    chapter = Column(String(200), nullable=False, default="")
    page = Column(Integer, nullable=True)
    kp_id = Column(
        BigInteger,
        ForeignKey("knowledge_points.id", ondelete="SET NULL"),
        nullable=True,
    )

    embedding = Column(JSON(none_as_null=True), nullable=True)
    embed_model = Column(String(80), nullable=False, default="")
    created_at = Column(DateTime, server_default=func.now())


