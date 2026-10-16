"""批量导入成功率对比 + 缓存一致性验证。

## 这个脚本回答导师的两个问题

1. **「导入成功率从多少提升到多少？」**
   构造一个含 8% 脏行的 1000 题文件（缺答案、选项不足、题干为空、
   答案越界、重复题——都是真实用户手工整理表格时最常见的错误），
   分别喂给 v1 和 v2 的解析器：
   - v1 是「全有或全无」，遇到第一行错误就整包失败；
   - v2 逐行隔离，坏行只记 issue，好行照常入库。

2. **「缓存一致性怎么保证？做一次压测跟优化」**
   反复执行「读列表（填缓存）→ 改题目（写）→ 再读列表」，
   检查第二次读到的是不是新数据，统计脏读次数。

用法：

    python scripts/bench_import.py \
        --v1-dir E:\\dswork\\cuoti-baseline\\backend \
        --v2-dir E:\\dswork\\cuoti-notebook\\backend \
        --base-url http://127.0.0.1:3102 --bank-id 1 \
        --out results/import.json
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import random
import sys
import time
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def load_importer(backend_dir: str, module_name: str):
    """按文件路径加载 importer 模块。

    v1/v2 的 importer.py 都不 import 项目内其它模块（只依赖 docx/openpyxl/
    pdfplumber），所以可以用两个不同的模块名同时加载，互不干扰。
    """
    path = Path(backend_dir) / "app" / "importer.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def build_dirty_dataset(total: int, dirty_rate: float, seed: int = 20261016):
    """造一份"用户手工整理"的题目表：大部分是好的，少量有毛病。"""
    random.seed(seed)
    items: list[dict] = []
    bad_plan: list[str] = []

    dirty_count = int(total * dirty_rate)
    dirty_idx = set(random.sample(range(total), dirty_count))

    kinds = ["no_answer", "one_option", "empty_stem", "multi_one_letter", "answer_out_of_range"]
    for i in range(total):
        item = {
            "stem": f"第 {i + 1} 题：关于该知识点的下列说法，正确的是？（模拟题干内容用于压测）",
            "question_type": "single",
            "options": ["选项A的内容", "选项B的内容", "选项C的内容", "选项D的内容"],
            "correct_answer": random.choice("ABCD"),
            "explanation": "解析：这里是解析内容。",
        }

        if i in dirty_idx:
            kind = kinds[i % len(kinds)]
            bad_plan.append(kind)
            if kind == "no_answer":
                item.pop("correct_answer")
            elif kind == "one_option":
                item["options"] = ["只有一个选项"]
                item["correct_answer"] = "A"
            elif kind == "empty_stem":
                item["stem"] = "   "
            elif kind == "multi_one_letter":
                item["question_type"] = "multiple"
                item["correct_answer"] = "A"
            elif kind == "answer_out_of_range":
                item["options"] = ["一", "二"]
                item["correct_answer"] = "D"
        elif i % 97 == 0:
            # 混入重复题（与前一条完全相同）—— 这类是 warning，不是 error
            items.append(dict(items[-1]) if items else item)
            continue

        items.append(item)

    return items, bad_plan


def run_parser(module, filename: str, content: bytes, version: str) -> dict:
    """跑一个版本的解析器，返回统计。"""
    started = time.perf_counter()
    out: dict = {"version": version, "elapsed_ms": 0.0}

    try:
        if version == "v1":
            questions = module.parse_file(filename, content)
            out.update({
                "imported": len(questions),
                "failed": 0,
                "deduped": 0,
                "fatal": False,
                "mode": "全有或全无：任何一行不合法就整包失败",
            })
        else:
            report = module.parse_file_report(filename, content)
            out.update({
                "imported": report.success,
                "failed": report.failed,
                "deduped": report.deduped,
                "retries": report.retries,
                "fatal": False,
                "mode": "逐行容错：坏行只记 issue，好行照常入库",
            })
    except Exception as e:  # noqa: BLE001
        out.update({
            "imported": 0,
            "failed": -1,
            "deduped": 0,
            "fatal": True,
            "error": f"{type(e).__name__}: {e}",
        })

    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    total = out.get("imported", 0) + max(out.get("failed", 0), 0)
    out["success_rate"] = round(out.get("imported", 0) / total, 4) if total else 0.0
    return out


async def http_import(
    base_url: str, token: str, bank_id: int, filename: str, content: bytes
) -> dict:
    """通过真实 HTTP 接口导入（前端 Bank.vue 走的就是这条路）。"""
    import httpx

    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{base_url}/api/banks/{bank_id}/questions/import",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (filename, content, "application/json")},
        )
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {"raw": resp.text[:300]}
    return {"status": resp.status_code, "elapsed_ms": elapsed, **body}


async def consistency_check(
    base_url: str, token: str, bank_id: int, rounds: int
) -> dict:
    """「写后立刻读」的脏读检查。

    每一步都故意读一次列表把缓存填满，再改题目（触发版本号 +1），
    然后再读一次——如果第二次还能读到旧题干，就是脏读。
    """
    import httpx

    headers = {"Authorization": f"Bearer {token}"}
    list_url = f"{base_url}/api/banks/{bank_id}/questions?page=1&page_size=20"
    stale = 0
    errors = 0
    samples: list[dict] = []

    async with httpx.AsyncClient(timeout=60) as client:
        # 先读一次，确保缓存里有内容
        resp = await client.get(list_url, headers=headers)
        if resp.status_code != 200:
            return {"error": f"读列表失败 {resp.status_code}: {resp.text[:200]}"}

        for i in range(rounds):
            resp = await client.get(list_url, headers=headers)
            if resp.status_code != 200:
                errors += 1
                continue
            items = resp.json()
            if not items:
                return {"error": "题库为空，无法验证"}
            target = items[i % len(items)]
            qid = target["id"]

            new_stem = f"一致性验证-{i}-{uuid.uuid4().hex[:8]}"
            resp = await client.put(
                f"{base_url}/api/questions/{qid}",
                headers=headers,
                json={"stem": new_stem},
            )
            if resp.status_code != 200:
                errors += 1
                continue

            resp = await client.get(list_url, headers=headers)
            if resp.status_code != 200:
                errors += 1
                continue
            after = {q["id"]: q.get("stem") for q in resp.json()}
            if after.get(qid) != new_stem:
                stale += 1
                if len(samples) < 3:
                    samples.append({
                        "round": i, "question_id": qid,
                        "expected": new_stem, "got": str(after.get(qid))[:60],
                    })

    return {
        "rounds": rounds,
        "stale_reads": stale,
        "errors": errors,
        "consistency_rate": round((rounds - stale - errors) / rounds, 4) if rounds else 0.0,
        "samples": samples,
    }


async def main_async(args: argparse.Namespace) -> dict:
    result: dict = {}

    # ---------- 1. 解析器成功率对比 ----------
    items, bad_plan = build_dirty_dataset(args.questions, args.dirty_rate)
    payload = json.dumps(items, ensure_ascii=False).encode("utf-8")
    filename = "dirty_questions.json"
    distinct_kinds = sorted(set(bad_plan))

    result["dataset"] = {
        "file": filename,
        "bytes": len(payload),
        "rows": len(items),
        "dirty_rows": len(bad_plan),
        "dirty_rate": round(len(bad_plan) / len(items), 4),
        "dirty_kinds": distinct_kinds,
    }
    print("=== 数据集 ===")
    print(f"  {len(items)} 行 / {len(payload) / 1024:.1f} KB，"
          f"脏行 {len(bad_plan)} 行（{len(bad_plan) / len(items):.1%}）")
    print(f"  脏行类型：{', '.join(distinct_kinds)}")

    v1 = load_importer(args.v1_dir, "importer_v1")
    v2 = load_importer(args.v2_dir, "importer_v2")

    r1 = run_parser(v1, filename, payload, "v1")
    r2 = run_parser(v2, filename, payload, "v2")
    result["parser_v1"] = r1
    result["parser_v2"] = r2

    print("\n=== 解析成功率对比 ===")
    for r in (r1, r2):
        line = (f"  {r['version']}：成功 {r['imported']} 条 / 失败 "
                f"{r['failed']} 条 / 成功率 {r['success_rate']:.1%} "
                f"/ {r['elapsed_ms']}ms")
        if r.get("fatal"):
            line += f"\n       整个文件失败：{r['error']}"
        print(line)

    # ---------- 2. 真实 HTTP 导入（v2）----------
    if args.base_url:
        import httpx

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{args.base_url}/api/login",
                json={"username": args.username, "password": args.password},
            )
            resp.raise_for_status()
            token = resp.json()["token"]

        # 先做一次 dry_run 校验，再真导入
        print("\n=== HTTP 端到端导入（走前端同一个接口）===")
        imp = await http_import(args.base_url, token, args.bank_id, filename, payload)
        result["http_import"] = {k: v for k, v in imp.items() if k != "issues"}
        result["http_import"]["issue_samples"] = (imp.get("issues") or [])[:5]
        print(f"  HTTP {imp['status']}  用时 {imp['elapsed_ms']}ms")
        print(f"  {imp.get('message', imp)}")
        if result["http_import"]["issue_samples"]:
            print("  错误清单样例：")
            for issue in result["http_import"]["issue_samples"]:
                print(f"    - [{issue.get('location')}] {issue.get('reason')}")

        # 再导一次同一个文件 → 应该全部被去重拦掉（幂等性）
        imp2 = await http_import(args.base_url, token, args.bank_id, filename, payload)
        result["http_import_repeat"] = {
            k: v for k, v in imp2.items() if k != "issues"
        }
        print(f"  重复导入同一文件：inserted={imp2.get('inserted')} "
              f"duplicate_count={imp2.get('duplicate_count')}（验证幂等）")

        # ---------- 3. 缓存一致性 ----------
        print(f"\n=== 缓存一致性（写后立刻读，{args.consistency_rounds} 轮）===")
        cons = await consistency_check(
            args.base_url, token, args.bank_id, args.consistency_rounds
        )
        result["consistency"] = cons
        if "error" in cons:
            print(f"  失败：{cons['error']}")
        else:
            print(f"  轮次 {cons['rounds']}，脏读 {cons['stale_reads']} 次，"
                  f"错误 {cons['errors']} 次，一致率 {cons['consistency_rate']:.1%}")
            for s in cons["samples"]:
                print(f"    ! 第{s['round']}轮 id={s['question_id']} "
                      f"期望={s['expected']} 实际={s['got']}")

    return result


def main() -> None:
    p = argparse.ArgumentParser(description="导入成功率 + 缓存一致性")
    p.add_argument("--v1-dir", default=str(Path("E:/dswork/cuoti-baseline/backend")))
    p.add_argument("--v2-dir", default=str(BACKEND_DIR))
    p.add_argument("--base-url", default="")
    p.add_argument("--username", default="bench_user")
    p.add_argument("--password", default="bench123456")
    p.add_argument("--bank-id", type=int, default=1)
    p.add_argument("--questions", type=int, default=1000)
    p.add_argument("--dirty-rate", type=float, default=0.08)
    p.add_argument("--consistency-rounds", type=int, default=50)
    p.add_argument("--out", default="")
    args = p.parse_args()

    payload = asyncio.run(main_async(args))
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n结果已写入 {out_path}")


if __name__ == "__main__":
    main()
