"""老库升级脚本的测试。

`upgrade_db.py` 解决的是一个很隐蔽的问题：`create_all` 只建新表、不给老表补索引，
所以升级上来之后新功能能跑但查询慢，而且**不报错**。

这里测三件事：
1. 全新库（create_all 建的）不该报"缺索引"——否则运维每次都会看到噪音；
2. 手工删掉一个索引之后，必须能识别出来；
3. 唯一约束不能被当成"缺索引"重复补（MySQL 里唯一约束本身就是索引）。
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

# 脚本放在 backend/scripts 下，不在包路径里，测试要显式加进去
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import upgrade_db  # noqa: E402

from app.db import Base  # noqa: E402
import app.models  # noqa: F401,E402


@pytest.fixture()
def sqlite_engine(tmp_path):
    """一个真实的 SQLite 库（不是内存库：inspect 需要能反复查同一份 schema）。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def test_fresh_database_has_no_missing_indexes(sqlite_engine):
    """刚 create_all 出来的库索引是齐的，不该报缺。"""
    assert upgrade_db.missing_indexes(inspect(sqlite_engine)) == []


def test_declared_indexes_covers_the_composite_ones():
    """模型里显式声明的联合索引必须都在检查范围内。

    这是脚本的核心价值所在：`Column(index=True)` 的单列索引大家都会注意，
    真正容易漏的是 `Index(...)` 声明的联合索引——它们恰恰是给新查询用的。
    """
    declared = upgrade_db.declared_indexes()
    assert declared["questions"]["ix_questions_bank_active_id"] == [
        "bank_id", "is_archived", "id",
    ]
    assert declared["answer_attempts"]["ix_attempts_user_question"] == [
        "user_id", "question_id",
    ]
    assert declared["question_user_states"]["ix_qus_user_wrong"] == [
        "user_id", "wrong_count",
    ]
    assert declared["user_kp_mastery"]["ix_mastery_user_p"] == ["user_id", "p_known"]


def test_detects_a_dropped_index(sqlite_engine):
    """删掉索引之后必须能认出来，并且列顺序要原样带出来。

    列顺序不能搞错：`(user_id, question_id)` 和 `(question_id, user_id)`
    是两个完全不同的索引，前者能支撑"按用户查"，后者不能。
    """
    with sqlite_engine.begin() as conn:
        conn.execute(text("DROP INDEX ix_questions_bank_active_id"))

    missing = upgrade_db.missing_indexes(inspect(sqlite_engine))
    assert ("questions", "ix_questions_bank_active_id",
            ["bank_id", "is_archived", "id"]) in missing
    # 只缺这一个，别的别误报
    assert len(missing) == 1


def test_unique_constraint_is_not_reported_as_missing_index(sqlite_engine):
    """唯一约束等同于索引，不能报"缺"。

    报缺的话脚本会再建一个同列的普通索引：写入变慢、磁盘白占，
    而且掩盖了"这个约束本来就有索引"的事实。
    """
    # users.username 是 unique=True，question_user_states 有联合唯一约束
    missing_names = {name for _, name, _ in upgrade_db.missing_indexes(inspect(sqlite_engine))}
    assert "uq_user_kp_mastery" not in missing_names
    assert not any("username" in n for n in missing_names), \
        f"把唯一约束当成缺索引了：{missing_names}"