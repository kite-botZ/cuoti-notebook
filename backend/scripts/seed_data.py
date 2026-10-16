"""生成压测数据集。

用法（在本目录的上一级执行）：

    python scripts/seed_data.py --questions 20000 --states 4000

设计要点：

- **固定随机种子**：优化前 / 优化后两组压测必须跑在同一份数据上，
  否则数字没有可比性。
- **独立数据库**：默认写 `cuoti_bench`，和开发库分开，不会污染你的数据。
- **批量插入**：用 SQLAlchemy Core 的 executemany，20000 条几秒钟就好，
  逐条 `db.add()` + commit 要跑十几分钟。
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="生成压测数据集")
    p.add_argument("--host", default=os.getenv("BENCH_DB_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.getenv("BENCH_DB_PORT", "3308")))
    p.add_argument("--user", default=os.getenv("BENCH_DB_USER", "root"))
    p.add_argument("--password", default=os.getenv("BENCH_DB_PASSWORD", ""))
    p.add_argument("--database", default=os.getenv("BENCH_DB_NAME", "cuoti_bench"))
    p.add_argument("--questions", type=int, default=20000, help="题目条数")
    p.add_argument("--states", type=int, default=4000, help="用户状态条数（错题/收藏/斩题）")
    p.add_argument("--username", default="bench_user")
    p.add_argument("--password-plain", default="bench123456")
    p.add_argument("--seed", type=int, default=20261016)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    random.seed(args.seed)

    # ---- 必须先设环境变量，再 import app.*（app.db 在导入时就会读 env）----
    os.environ["APP_ENV"] = "production"
    os.environ["DB_HOST"] = args.host
    os.environ["DB_PORT"] = str(args.port)
    os.environ["DB_USER"] = args.user
    os.environ["DB_PASSWORD"] = args.password
    os.environ["DB_NAME"] = args.database
    os.environ.setdefault("JWT_SECRET_KEY", "bench-secret-key-for-load-test-only")
    os.environ["CACHE_DISABLED"] = "1"  # 造数阶段不需要缓存
    sys.path.insert(0, str(BACKEND_DIR))

    import bcrypt
    import pymysql
    from sqlalchemy import insert

    # ---- 1. 建库 ----
    conn = pymysql.connect(
        host=args.host, port=args.port, user=args.user,
        password=args.password, charset="utf8mb4",
    )
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{args.database}` "
            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    conn.commit()
    conn.close()

    from app.db import Base, engine
    from app.models import Question, QuestionBank, QuestionUserState, User

    print(f"[1/4] 重建表结构：{args.database}@{args.host}:{args.port}")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    # ---- 2. 用户 + 题库 ----
    pwd_hash = bcrypt.hashpw(args.password_plain.encode(), bcrypt.gensalt()).decode()
    with engine.begin() as conn:
        result = conn.execute(
            insert(User).values(username=args.username, password=pwd_hash)
        )
        user_id = result.inserted_primary_key[0]
        result = conn.execute(
            insert(QuestionBank).values(
                user_id=user_id, name="压测题库（2万题）",
                subject="综合", description="性能测试数据",
            )
        )
        bank_id = result.inserted_primary_key[0]
    print(f"[2/4] 用户 id={user_id}，题库 id={bank_id}")

    # ---- 3. 题目 ----
    subjects = ["高等数学", "计算机网络", "数据结构", "操作系统", "数据库原理", "线性代数"]
    templates = [
        "{s}中关于「{t}」的说法，正确的是？",
        "下列关于{s}「{t}」的描述，哪一项是错误的？",
        "在{s}中，{t}的主要作用是？",
        "关于{s}的{t}，下列说法不正确的是？",
    ]
    topics = [
        "时间复杂度", "索引下推", "三次握手", "死锁预防", "缓存一致性",
        "红黑树", "B+树", "事务隔离级别", "TCP 拥塞控制", "页面置换算法",
        "拉格朗日乘子", "特征值与特征向量", "矩阵秩", "极限存在性", "多元复合求导",
    ]
    types = ["single"] * 7 + ["multiple"] * 2 + ["judge"] + ["blank"] + ["short"]

    print(f"[3/4] 生成 {args.questions} 道题 ...")
    start = time.perf_counter()
    total = 0
    chunk: list[dict] = []
    for i in range(args.questions):
        qtype = types[i % len(types)]
        stem = random.choice(templates).format(
            s=random.choice(subjects), t=random.choice(topics)
        ) + f"（第 {i + 1} 题）"
        if qtype in ("blank", "short"):
            options: list[str] = []
        elif qtype == "judge":
            options = ["正确", "错误"]
        else:
            options = [f"选项内容 {c}：{random.choice(topics)}的相关描述" for c in "ABCD"]
        chunk.append({
            "bank_id": bank_id,
            "stem": stem,
            "question_type": qtype,
            "options": options,
            "correct_answer": random.choice(["A", "B", "C", "D"]) if qtype in ("single", "multiple") else "参考答案内容",
            "explanation": "解析：" + random.choice(topics) + "，详见教材相关章节。" * 2,
            "is_archived": False,
        })
        if len(chunk) >= 2000:
            with engine.begin() as conn:
                conn.execute(insert(Question), chunk)
            total += len(chunk)
            chunk.clear()
    if chunk:
        with engine.begin() as conn:
            conn.execute(insert(Question), chunk)
        total += len(chunk)
    print(f"      完成 {total} 道，用时 {time.perf_counter() - start:.1f}s")

    # ---- 4. 用户状态：错题 / 收藏 / 斩题 ----
    print(f"[4/4] 生成 {args.states} 条用户状态 ...")
    with engine.begin() as conn:
        rows = conn.execute(
            # 只取一部分题目 id，模拟"用户只做过其中一部分"
            Question.__table__.select()
            .with_only_columns(Question.__table__.c.id)
            .where(Question.__table__.c.bank_id == bank_id)
            .limit(args.questions)
        ).fetchall()
    all_ids = [r[0] for r in rows]
    sample = random.sample(all_ids, min(args.states, len(all_ids)))

    states = []
    for qid in sample:
        states.append({
            "user_id": user_id,
            "question_id": qid,
            "is_favorite": random.random() < 0.15,
            "is_cut": random.random() < 0.10,
            "note": "笔记：" + random.choice(topics) if random.random() < 0.2 else "",
            "wrong_count": random.randint(1, 5),
        })
    with engine.begin() as conn:
        for i in range(0, len(states), 2000):
            conn.execute(insert(QuestionUserState), states[i:i + 2000])

    print("\n=== 数据集就绪 ===")
    print(f"  用户名：{args.username} / 密码：{args.password_plain}")
    print(f"  题库 id：{bank_id}   题目 {total} 道   用户状态 {len(states)} 条")


if __name__ == "__main__":
    main()
