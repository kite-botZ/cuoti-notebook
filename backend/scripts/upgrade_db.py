"""老库升级助手：把「模型里声明了、但库里没有」的索引补齐。

## 为什么需要这个脚本

`Base.metadata.create_all()` 只会**新建缺失的表**，不会给**已存在的表**补索引。
所以从旧版本升级上来（或者把库从一台机器搬到另一台）时会出现这种情况：

  - 表是旧的，索引还是旧的；
  - 新加的表（知识点 / 讲义 / 掌握度）倒是会自动建好。

结果是新功能能跑，但查询慢——因为缺的正好是支撑那些查询的索引。
这类问题不会报错，只会"慢"，很容易被忽略，所以单独做一个可重复执行的脚本。

## 用法

    cd backend
    python scripts/upgrade_db.py            # 只看差什么，不改库
    python scripts/upgrade_db.py --apply    # 真的执行 ALTER

连的是 `backend/.env` 里配置的那个库（和 App 同一套配置），
所以**对着生产库跑之前先不带 --apply 看一眼**。

脚本是幂等的：已经存在的索引会跳过，不会重复建、也不会报错。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text  # noqa: E402

from app.db import Base, engine  # noqa: E402
import app.models  # noqa: F401,E402  必须导入，否则 Base.metadata 里没有模型


def declared_indexes() -> dict[str, dict[str, list[str]]]:
    """模型里声明的索引：{表名: {索引名: [列名...]}}。

    包含两类，都要检查：
    - `Column(..., index=True)` 生成的单列索引；
    - `Index(...)` 显式声明的联合索引。
    """
    result: dict[str, dict[str, list[str]]] = {}
    for table in Base.metadata.sorted_tables:
        entries: dict[str, list[str]] = {}
        for index in table.indexes:
            entries[index.name] = [c.name for c in index.columns]
        result[table.name] = entries
    return result


def missing_indexes(
    inspector, existing_tables: set[str] | None = None
) -> list[tuple[str, str, list[str]]]:
    """算出「模型里声明了、但库里没有」的索引。

    抽成独立函数是为了能单测（见 tests/test_upgrade_db.py）：
    只依赖一个 SQLAlchemy inspector，不依赖 main() 里的打印和 ALTER。
    """
    if existing_tables is None:
        existing_tables = set(inspector.get_table_names())

    missing: list[tuple[str, str, list[str]]] = []
    for table, indexes in declared_indexes().items():
        if table not in existing_tables:
            continue
        have = {i["name"] for i in inspector.get_indexes(table)}
        # 唯一约束也算"索引已经有了"：MySQL 里唯一约束就是唯一索引，
        # 否则会给同一批列再建一个重复索引（白占写入开销）
        have |= {u["name"] for u in inspector.get_unique_constraints(table)}
        for name, columns in indexes.items():
            if name not in have:
                missing.append((table, name, columns))
    return missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="真的执行 ALTER（默认只报告不修改）")
    args = parser.parse_args()

    print(f"目标库：{engine.url.render_as_string(hide_password=True)}")
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    declared = declared_indexes()
    missing_tables = [t for t in declared if t not in existing_tables]
    if missing_tables:
        # 这些表会在应用启动时由 create_all 建好（连带索引），这里不用管
        print(f"\n库里还没有的表（启动应用时会自动建，含索引）：{', '.join(missing_tables)}")

    missing = missing_indexes(inspector, existing_tables)

    if not missing:
        print("\n索引齐全，不需要处理。")
        return 0

    print(f"\n缺 {len(missing)} 个索引：")
    for table, name, columns in missing:
        print(f"  {table:<24} {name:<28} ({', '.join(columns)})")

    if not args.apply:
        print("\n（上面只是预览，加 --apply 才会真的建）")
        return 0

    with engine.begin() as conn:
        for table, name, columns in missing:
            cols = ", ".join(f"`{c}`" for c in columns)
            sql = f"ALTER TABLE `{table}` ADD INDEX `{name}` ({cols})"
            print(f"  执行：{sql}")
            conn.execute(text(sql))

    print("\n完成。再跑一次本脚本应该显示「索引齐全」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())