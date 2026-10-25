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


def declared_string_widths() -> dict[str, dict[str, int]]:
    """模型里声明的字符串列宽度：{表名: {列名: 长度}}。

    只收 `String(n)` 这种带明确长度的；`Text` 没有长度，不需要检查。
    """
    result: dict[str, dict[str, int]] = {}
    for table in Base.metadata.sorted_tables:
        entries: dict[str, int] = {}
        for column in table.columns:
            length = getattr(column.type, "length", None)
            if isinstance(length, int):
                entries[column.name] = length
        result[table.name] = entries
    return result


def narrow_columns(
    inspector, existing_tables: set[str] | None = None
) -> list[tuple[str, str, int, int]]:
    """找出「库里的列比模型声明的窄」的列：[(表, 列, 库里宽度, 模型宽度)]。

    为什么需要查这个（而不只是查索引）：

    create_all 既然不补索引，就更不会改列宽。于是代码里放宽了
    `questions.correct_answer`（50 → 255）、`answer_attempts.selected_answer`
    （255 → 500）之后，**老库、生产库还是旧宽度**，写入超长值就是
    MySQL 1406 Data too long → 500，而且整个事务回滚、这次作答全丢。
    这类问题在 SQLite 上永远测不出来（SQLite 不校验长度），只有对着
    MySQL 才会暴露——正好是最不该出事的环境。

    比模型**宽**的列不算问题（只是浪费一点空间），不报告、不缩窄：
    缩窄是有数据丢失风险的破坏性操作，绝不该由这个脚本自动做。
    """
    if existing_tables is None:
        existing_tables = set(inspector.get_table_names())

    narrow: list[tuple[str, str, int, int]] = []
    for table, columns in declared_string_widths().items():
        if table not in existing_tables:
            continue
        actual = {c["name"]: c["type"] for c in inspector.get_columns(table)}
        for name, want in columns.items():
            col_type = actual.get(name)
            have = getattr(col_type, "length", None)
            if isinstance(have, int) and have < want:
                narrow.append((table, name, have, want))
    return narrow


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
    narrow = narrow_columns(inspector, existing_tables)

    if not missing and not narrow:
        print("\n索引齐全、列宽也够，不需要处理。")
        return 0

    if missing:
        print(f"\n缺 {len(missing)} 个索引：")
        for table, name, columns in missing:
            print(f"  {table:<24} {name:<28} ({', '.join(columns)})")

    if narrow:
        print(f"\n有 {len(narrow)} 个列比模型窄（写入超长值会报 1406 并回滚整个事务）：")
        for table, name, have, want in narrow:
            print(f"  {table:<24} {name:<24} 库={have}  模型={want}")

    if not args.apply:
        print("\n（上面只是预览，加 --apply 才会真的改）")
        return 0

    with engine.begin() as conn:
        for table, name, columns in missing:
            cols = ", ".join(f"`{c}`" for c in columns)
            sql = f"ALTER TABLE `{table}` ADD INDEX `{name}` ({cols})"
            print(f"  执行：{sql}")
            conn.execute(text(sql))

        # SQLite 不支持 MODIFY COLUMN，而且 SQLite 本来也不校验长度，
        # 所以这条只在 MySQL 上执行。
        if engine.dialect.name == "mysql":
            for table, name, _have, want in narrow:
                col = next(c for c in inspector.get_columns(table) if c["name"] == name)
                if col.get("default") is not None:
                    # MODIFY COLUMN 会**重写整个列定义**：不把默认值原样带上，
                    # 默认值就被抹掉了。而 inspector 给出的默认值形态（带不带引号）
                    # 跟列类型有关，拼错就是一条坏 DDL。这种事不值得"顺手做"，
                    # 让用户自己确认更安全。
                    print(f"  跳过 {table}.{name}：该列有默认值（{col['default']}），"
                          f"请手工 ALTER，避免脚本把默认值抹掉")
                    continue
                null_sql = "NULL" if col.get("nullable") else "NOT NULL"
                sql = (
                    f"ALTER TABLE `{table}` MODIFY COLUMN `{name}` "
                    f"VARCHAR({want}) {null_sql}"
                )
                print(f"  执行：{sql}")
                conn.execute(text(sql))
        elif narrow:
            print("  （当前是 SQLite，列宽不需要/无法修改，已跳过）")

    print("\n完成。再跑一次本脚本应该显示「索引齐全、列宽也够」。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())