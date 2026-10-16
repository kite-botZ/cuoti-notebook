"""压测工具库：异步并发请求 + 分位数统计。

## 为什么不用 locust

这个项目只压三四个具体接口，自写 asyncio + httpx 能精确控制并发模型，
而且可以顺便量 **首字节时间（TTFB）**——`/api/ai/explain` 是 SSE 流式接口，
用户体感快慢主要取决于第一个字什么时候出来，而不是整包什么时候结束。
locust 默认只统计整包耗时，量不到 TTFB。

## 统计口径

- `p50 / p95 / p99`：用线性插值算分位数，和 Prometheus histogram_quantile 口径一致
- `qps`：总请求数 / 墙钟时间
- `ok_rate`：HTTP 2xx 占比
- `bytes`：平均响应体大小（用来解释"为什么分页能把耗时打下来"）
"""

from __future__ import annotations

import asyncio
import math
import statistics
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class Result:
    ok: bool
    status: int
    ttfb_ms: float
    total_ms: float
    bytes: int
    error: str = ""


@dataclass
class Report:
    name: str
    count: int = 0
    ok: int = 0
    ttfb: list[float] = field(default_factory=list)
    total: list[float] = field(default_factory=list)
    sizes: list[int] = field(default_factory=list)
    wall_s: float = 0.0
    errors: dict[str, int] = field(default_factory=dict)

    def add(self, r: Result) -> None:
        self.count += 1
        if r.ok:
            self.ok += 1
            self.ttfb.append(r.ttfb_ms)
            self.total.append(r.total_ms)
            self.sizes.append(r.bytes)
        else:
            key = f"{r.status} {r.error}"[:80]
            self.errors[key] = self.errors.get(key, 0) + 1

    def to_dict(self) -> dict:
        def pct(values: list[float], p: float) -> float:
            if not values:
                return 0.0
            s = sorted(values)
            k = (len(s) - 1) * p
            f, c = math.floor(k), math.ceil(k)
            if f == c:
                return round(s[int(k)], 2)
            return round(s[f] * (c - k) + s[c] * (k - f), 2)

        return {
            "name": self.name,
            "requests": self.count,
            "ok": self.ok,
            "ok_rate": round(self.ok / self.count, 4) if self.count else 0.0,
            "wall_s": round(self.wall_s, 3),
            "qps": round(self.ok / self.wall_s, 1) if self.wall_s else 0.0,
            "ttfb_ms": {
                "avg": round(statistics.fmean(self.ttfb), 2) if self.ttfb else 0.0,
                "p50": pct(self.ttfb, 0.50),
                "p95": pct(self.ttfb, 0.95),
                "p99": pct(self.ttfb, 0.99),
                "max": round(max(self.ttfb), 2) if self.ttfb else 0.0,
            },
            "total_ms": {
                "avg": round(statistics.fmean(self.total), 2) if self.total else 0.0,
                "p50": pct(self.total, 0.50),
                "p95": pct(self.total, 0.95),
                "p99": pct(self.total, 0.99),
                "max": round(max(self.total), 2) if self.total else 0.0,
            },
            "avg_bytes": int(statistics.fmean(self.sizes)) if self.sizes else 0,
            "errors": self.errors,
        }


async def one_request(client: httpx.AsyncClient, method: str, url: str, **kw) -> Result:
    """发一个请求，分别记录 TTFB 和整包耗时。

    流式接口用 `client.stream()`：`aiter_bytes()` 拿第一块的时间就是 TTFB。
    """
    start = time.perf_counter()
    try:
        async with client.stream(method, url, **kw) as resp:
            size = 0
            ttfb = None
            async for chunk in resp.aiter_bytes():
                if ttfb is None:
                    ttfb = (time.perf_counter() - start) * 1000
                size += len(chunk)
            end = (time.perf_counter() - start) * 1000
            return Result(
                ok=200 <= resp.status_code < 300,
                status=resp.status_code,
                ttfb_ms=ttfb if ttfb is not None else end,
                total_ms=end,
                bytes=size,
                error="" if resp.status_code < 400 else (await _safe_text(resp)),
            )
    except Exception as e:  # noqa: BLE001
        end = (time.perf_counter() - start) * 1000
        return Result(False, 0, end, end, 0, f"{type(e).__name__}: {e}")


async def _safe_text(resp: httpx.Response) -> str:
    try:
        body = await resp.aread()
        return body.decode("utf-8", "ignore")[:120]
    except Exception:  # noqa: BLE001
        return ""


async def run_load(
    name: str,
    method: str,
    url: str,
    *,
    concurrency: int = 10,
    total: int = 100,
    headers: dict | None = None,
    json_body: dict | None = None,
    data: dict | None = None,
    timeout: float = 300.0,
) -> Report:
    """以固定并发跑 total 个请求，返回统计报告。"""
    report = Report(name=name)
    sem = asyncio.Semaphore(concurrency)

    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        async def worker(i: int) -> None:
            async with sem:
                r = await one_request(
                    client, method, url, headers=headers, json=json_body, data=data
                )
                report.add(r)

        start = time.perf_counter()
        await asyncio.gather(*(worker(i) for i in range(total)))
        report.wall_s = time.perf_counter() - start

    return report


def fmt(report: dict) -> str:
    """一行式打印，方便贴进对比表。"""
    t = report["total_ms"]
    return (
        f"{report['name']:<28} "
        f"n={report['ok']:<5} "
        f"avg={t['avg']:>9.1f}ms "
        f"p50={t['p50']:>9.1f} "
        f"p95={t['p95']:>9.1f} "
        f"p99={t['p99']:>9.1f} "
        f"qps={report['qps']:>8.1f} "
        f"avg_bytes={report['avg_bytes']:>9}"
    )
