"""精确测量 AI 解析的「单次生成」耗时。

为什么要单独测：第一次调用 Ollama 会把模型权重加载进显存（本机 gemma3:4b
冷加载约 30 秒），如果把这个时间算进「单次生成耗时」，数字会虚高、
面试官一追问「模型常驻的时候多久」就答不上来。

这个脚本对 N 道**互不相同**的题目依次请求（每题都是冷缓存），
分别记录每次耗时，最后给出「常驻后的单次生成耗时」中位数。

用法：
    python scripts/measure_ai_single.py --base-url http://127.0.0.1:3102 \
        --questions 101,102,103
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import httpx


async def measure(base_url: str, token: str, question_id: int) -> float:
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=600) as client:
        async with client.stream(
            "POST",
            f"{base_url}/api/ai/explain",
            headers={"Authorization": f"Bearer {token}"},
            json={"question_id": question_id, "user_answer": "A"},
        ) as resp:
            resp.raise_for_status()
            size = 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
    elapsed = (time.perf_counter() - started) * 1000
    print(f"  题目 {question_id}: {elapsed:>9.0f} ms  响应 {size} 字节")
    return elapsed


async def main_async(args: argparse.Namespace) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{args.base_url}/api/login",
            json={"username": args.username, "password": args.password},
        )
        resp.raise_for_status()
        token = resp.json()["token"]

    ids = [int(x) for x in args.questions.split(",") if x.strip()]
    print(f"依次请求 {len(ids)} 道互不相同的题目（每题都是冷缓存）：")
    times = []
    for qid in ids:
        times.append(await measure(args.base_url, token, qid))

    warm = times[1:] if len(times) > 1 else times
    out = {
        "first_call_ms": round(times[0], 1),
        "all_ms": [round(t, 1) for t in times],
        "warm_single_median_ms": round(statistics.median(warm), 1),
        "warm_single_min_ms": round(min(warm), 1),
        "warm_single_max_ms": round(max(warm), 1),
    }
    print("\n=== 结果 ===")
    print(f"  首次调用（含模型冷加载）：{out['first_call_ms'] / 1000:.1f}s")
    print(f"  模型常驻后的单次生成：中位数 "
          f"{out['warm_single_median_ms'] / 1000:.1f}s "
          f"（{out['warm_single_min_ms'] / 1000:.1f}s ~ "
          f"{out['warm_single_max_ms'] / 1000:.1f}s）")

    if args.out:
        from pathlib import Path
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  已写入 {p}")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="测量 AI 单次生成耗时")
    p.add_argument("--base-url", default="http://127.0.0.1:3102")
    p.add_argument("--username", default="bench_user")
    p.add_argument("--password", default="bench123456")
    p.add_argument("--questions", default="101,102,103")
    p.add_argument("--out", default="")
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
