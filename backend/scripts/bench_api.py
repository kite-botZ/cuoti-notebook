"""接口压测：优化前(v1) vs 优化后(v2)。

用法：

    # 优化后（带缓存 + 分页）
    python scripts/bench_api.py --base-url http://127.0.0.1:3102 --bank-id 1 \
        --out results/v2_api.json

    # 优化前（基线代码）
    python scripts/bench_api.py --base-url http://127.0.0.1:3101 --bank-id 1 \
        --out results/v1_api.json --skip-paged

两个服务跑的是**同一份数据**（不同库、同样 2 万题），
所以差异只来自代码，不来自数据。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_lib import Report, Result, fmt, run_load  # noqa: E402

import httpx  # noqa: E402


async def login(base_url: str, username: str, password: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base_url}/api/login",
            json={"username": username, "password": password},
        )
        resp.raise_for_status()
        return resp.json()["token"]


async def burst_same_question(
    base_url: str,
    token: str,
    question_id: int,
    concurrency: int,
) -> dict:
    """同一道题并发请求 AI 解析，数一数到底调用了几次本地模型。

    判断依据：命中缓存的响应里带 `"cached": true`，没带的就是真回源了。
    这是防击穿机制最直接的证据。
    """
    report = Report(name=f"ai_explain_burst_x{concurrency}")
    sem = asyncio.Semaphore(concurrency)
    model_calls = 0
    cache_hits = 0
    lock = asyncio.Lock()

    async with httpx.AsyncClient(timeout=600) as client:
        async def worker() -> None:
            nonlocal model_calls, cache_hits
            async with sem:
                start = time.perf_counter()
                hit = False
                ttfb = None
                status = 0
                body = bytearray()
                try:
                    async with client.stream(
                        "POST",
                        f"{base_url}/api/ai/explain",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"question_id": question_id, "user_answer": "A"},
                    ) as resp:
                        status = resp.status_code
                        async for chunk in resp.aiter_bytes():
                            if ttfb is None:
                                ttfb = (time.perf_counter() - start) * 1000
                            body.extend(chunk)
                except Exception as e:  # noqa: BLE001
                    async with lock:
                        report.add(Result(
                            False, 0, 0, (time.perf_counter() - start) * 1000, 0, str(e)
                        ))
                    return
                # 累积完整响应体之后再判断：SSE 事件可能被 TCP 拆成多个 chunk，
                # 逐块搜索 "cached" 标记会漏判。
                hit = b'"cached": true' in bytes(body) or b'"cached":true' in bytes(body)
                size = len(body)
                end = (time.perf_counter() - start) * 1000
                async with lock:
                    if hit:
                        cache_hits += 1
                    else:
                        model_calls += 1
                    report.add(Result(
                        ok=200 <= status < 300, status=status,
                        ttfb_ms=ttfb if ttfb is not None else end,
                        total_ms=end, bytes=size,
                    ))

        start = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(concurrency)))
        report.wall_s = time.perf_counter() - start

    out = report.to_dict()
    out["model_calls"] = model_calls
    out["cache_hits"] = cache_hits
    out["concurrency"] = concurrency
    return out


async def main_async(args: argparse.Namespace) -> dict:
    base = args.base_url.rstrip("/")
    token = await login(base, args.username, args.password)
    headers = {"Authorization": f"Bearer {token}"}
    results: list[dict] = []

    list_url = f"{base}/api/banks/{args.bank_id}/questions"
    paged_url = f"{list_url}?page=1&page_size={args.page_size}"

    # ---------- 1. 题目列表：全量（v1 语义，v2 保留的兼容路径）----------
    if not args.skip_list:
        r = await run_load(
            "list_all(全量返回)", "GET", list_url,
            concurrency=args.concurrency, total=args.total, headers=headers,
        )
        results.append(r.to_dict())
        print(fmt(results[-1]))

    if not args.skip_list and not args.skip_paged:
        # ---------- 2. 题目列表：分页（首次，缓存未命中）----------
        r = await run_load(
            f"list_page{args.page_size}(分页冷)", "GET", paged_url,
            concurrency=args.concurrency, total=args.total, headers=headers,
        )
        results.append(r.to_dict())
        print(fmt(results[-1]))

        # ---------- 3. 题目列表：分页（命中缓存）----------
        r = await run_load(
            f"list_page{args.page_size}(分页热缓存)", "GET", paged_url,
            concurrency=args.concurrency, total=args.total, headers=headers,
        )
        results.append(r.to_dict())
        print(fmt(results[-1]))

    # ---------- 4/5. AI 解析：冷 / 热 ----------
    if args.ai_question and args.ai_total > 0:
        ai_url = f"{base}/api/ai/explain"
        body = {"question_id": args.ai_question, "user_answer": "A"}

        # 先打一次确保缓存已被填充（v2 会写入，v1 什么都没发生）
        await run_load("ai_warmup", "POST", ai_url, concurrency=1, total=1,
                       headers=headers, json_body=body)

        r = await run_load(
            "ai_explain(命中缓存)", "POST", ai_url,
            concurrency=args.concurrency, total=args.ai_total, headers=headers,
            json_body=body,
        )
        results.append(r.to_dict())
        print(fmt(results[-1]))

    # ---------- 6. 同一道题并发：模型调用次数（防击穿验证）----------
    if args.ai_concurrency > 0 and (args.ai_question or args.burst_question):
        # 注意：必须用一道「还没被缓存过」的题，否则测的是命中缓存而不是防击穿。
        # --burst-question 传 0 表示随机抽一道（避开 ai_question）。
        burst_q = args.burst_question
        if not burst_q:
            candidates = [q for q in range(1, 20001) if q != args.ai_question]
            import random as _random
            burst_q = _random.choice(candidates)
        out = await burst_same_question(
            base, token, burst_q, args.ai_concurrency
        )
        out["question_id"] = burst_q
        results.append(out)
        print(
            f"{out['name']:<28} "
            f"n={out['ok']:<5} wall={out['wall_s']:>7.2f}s "
            f"模型调用={out['model_calls']}次 命中缓存={out['cache_hits']}次 "
            f"p95={out['total_ms']['p95']}ms"
        )

    return {"base_url": base, "scenarios": results}


def main() -> None:
    p = argparse.ArgumentParser(description="接口压测")
    p.add_argument("--base-url", required=True)
    p.add_argument("--username", default="bench_user")
    p.add_argument("--password", default="bench123456")
    p.add_argument("--bank-id", type=int, default=1)
    p.add_argument("--ai-question", type=int, default=0, help="AI 解析压测用的题目 id")
    p.add_argument("--burst-question", type=int, default=0,
                   help="防击穿测试用的题目 id；0 表示随机抽一道冷题")
    p.add_argument("--ai-concurrency", type=int, default=10)
    p.add_argument("--ai-total", type=int, default=30)
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--total", type=int, default=30)
    p.add_argument("--page-size", type=int, default=20)
    p.add_argument("--skip-paged", action="store_true", help="v1 没有分页，跳过")
    p.add_argument("--skip-list", action="store_true",
                   help="只跑 AI 相关场景（列表全量太慢时用）")
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
