"""Redis 缓存层。

三条设计原则：

1. **降级优先**：Redis 连不上 / 超时 / 没装 redis-py 时，所有操作静默回源，
   业务不受任何影响。缓存是加速手段，不能成为单点。

2. **一致性靠「版本号 + 写后删」**：写路径只做一次 `INCR 题库版本号`，
   读路径把版本号拼进 key。版本号一变，旧 key 全部自然失效，
   避免 `KEYS`/`SCAN` 批量删除在大 key 空间下阻塞 Redis 单线程。
   版本号 key 不设过期时间：Redis 自身重启会清空所有数据，
   此时不存在脏 key，版本号回到 0 也是安全的。

3. **防雪崩 + 防击穿**：
   - TTL 加 ±10% 随机抖动，避免同一批 key 同时失效；
   - 热点 key 用 `SET NX EX` 互斥锁重建，并发请求只有一个真正回源，
     其余等待缓存回填，避免把压力打到本地大模型上。
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from typing import Any, Callable

try:  # 没装 redis-py 时整体降级，不影响服务启动
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore[assignment]


PREFIX = os.getenv("CACHE_PREFIX", "cuoti")

# 过期时间（秒）
EXPLAIN_TTL = int(os.getenv("CACHE_EXPLAIN_TTL", "86400"))  # AI 解析结果：24h
QLIST_TTL = int(os.getenv("CACHE_QLIST_TTL", "300"))        # 题目列表页：5min
BANK_TTL = int(os.getenv("CACHE_BANK_TTL", "120"))          # 题库列表：2min

JITTER = 0.1  # TTL 抖动比例


def content_hash(*parts: Any) -> str:
    """把若干字段拼成短哈希，用于「内容变了 key 就变」的自动失效。"""
    raw = "\x1f".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


class Cache:
    """Redis 封装。所有方法在 Redis 不可用时都不会抛异常。"""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.timeout = float(os.getenv("CACHE_TIMEOUT", "0.1"))
        self._client: Any = None
        self._local = {"hit": 0, "miss": 0, "error": 0, "bypass": 0}

        if redis is None or os.getenv("CACHE_DISABLED") == "1":
            return
        try:
            self._client = redis.Redis.from_url(
                self.url,
                decode_responses=True,
                socket_timeout=self.timeout,
                socket_connect_timeout=float(os.getenv("CACHE_CONNECT_TIMEOUT", "0.2")),
                health_check_interval=30,
                # 显式用 RESP2：redis-py 8 默认走 RESP3，握手时发 HELLO 3，
                # 而 Redis 5 没有 HELLO 命令（RESP3 是 Redis 6 才有的），
                # 会直接报 "unknown command `HELLO`"。缓存只用 GET/SET/DEL/INCR，
                # RESP2 完全够用，没必要为了协议版本绑死 Redis 6+。
                protocol=int(os.getenv("CACHE_PROTOCOL", "2")),
            )
            self._client.ping()
        except Exception:
            # 启动时连不上就先降级；后续请求会再尝试（连接池会自动重连）
            self._client = None

    # ---------------------------------------------------------- 基础属性

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def _safe(self, fn: Callable[[], Any], default: Any = None) -> Any:
        if self._client is None:
            return default
        try:
            return fn()
        except Exception:
            # 任何 Redis 异常都不向上抛：记一笔错误，调用方走回源逻辑
            self._local["error"] += 1
            return default

    # ---------------------------------------------------------- 读写

    def get_json(self, key: str) -> Any | None:
        raw = self._safe(lambda: self._client.get(key))
        if raw is None:
            self._local["miss"] += 1
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            self._local["miss"] += 1
            return None
        self._local["hit"] += 1
        return value

    def set_json(self, key: str, value: Any, ttl: int) -> bool:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        # TTL 抖动，避免缓存雪崩
        ttl = max(1, int(ttl * (1 + random.uniform(-JITTER, JITTER))))
        ok = self._safe(lambda: self._client.set(key, payload, ex=ttl))
        return bool(ok)

    def get_raw(self, key: str) -> str | None:
        return self._safe(lambda: self._client.get(key))

    def set_raw(self, key: str, value: str, ttl: int | None = None) -> bool:
        ok = self._safe(
            lambda: self._client.set(key, value, ex=ttl) if ttl else self._client.set(key, value)
        )
        return bool(ok)

    def delete(self, *keys: str) -> int:
        if not keys:
            return 0
        return int(self._safe(lambda: self._client.delete(*keys)) or 0)

    def incr(self, key: str, amount: int = 1) -> int:
        return int(self._safe(lambda: self._client.incrby(key, amount)) or 0)

    # ---------------------------------------------------------- 版本号

    def bank_version(self, bank_id: int) -> int:
        """取题库当前版本号；不存在时初始化为 0。"""
        key = f"{PREFIX}:ver:bank:{bank_id}"
        v = self._safe(lambda: self._client.get(key))
        if v is None:
            # 只在缺失时写一次，NX 防止并发覆盖别人的递增
            self._safe(lambda: self._client.set(key, "0", nx=True))
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    def bump_bank_version(self, bank_id: int) -> int:
        """题库内容发生写操作时调用：版本号 +1，所有旧缓存 key 立即失效。"""
        return self.incr(f"{PREFIX}:ver:bank:{bank_id}")

    # ---------------------------------------------------------- 防击穿

    def acquire_lock(self, name: str, ttl: int = 60) -> bool:
        """`SET NX EX` 抢锁；抢到的人负责回源并回填缓存。"""
        key = f"{PREFIX}:lock:{name}"
        return bool(self._safe(lambda: self._client.set(key, "1", nx=True, ex=ttl)))

    def release_lock(self, name: str) -> None:
        self._safe(lambda: self._client.delete(f"{PREFIX}:lock:{name}"))

    def wait_for(self, key: str, timeout: float = 30.0, interval: float = 0.05) -> Any | None:
        """等别人回填缓存（防击穿里「没抢到锁」的分支）。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.get_json(key)
            if value is not None:
                return value
            time.sleep(interval)
        return None

    # ---------------------------------------------------------- 统计

    def stats(self) -> dict:
        """应用侧命中率 + Redis 服务端命中率，两者都要能对上。"""
        local = dict(self._local)
        total = local["hit"] + local["miss"]
        local["hit_rate"] = round(local["hit"] / total, 4) if total else 0.0

        info: dict = {}
        if self._client is not None:
            raw = self._safe(lambda: self._client.info("stats"))
            if raw:
                hits = int(raw.get("keyspace_hits", 0))
                misses = int(raw.get("keyspace_misses", 0))
                info = {
                    "redis_keyspace_hits": hits,
                    "redis_keyspace_misses": misses,
                    "redis_hit_rate": round(hits / (hits + misses), 4) if hits + misses else 0.0,
                }
        return {**local, **info, "enabled": self.enabled}

    def reset_stats(self) -> None:
        for k in self._local:
            self._local[k] = 0
        self._safe(lambda: self._client.config_resetstat())

    def clear_namespace(self) -> int:
        """删掉本前缀下的所有 key。

        只给测试和运维用（线上要清缓存请用 `CACHE_PREFIX` 换命名空间，
        或者直接改题库版本号）。用 `SCAN` 游标分批删，不用 `KEYS`，
        避免在大 key 空间下把 Redis 单线程堵住。
        """
        if self._client is None:
            return 0
        removed = 0
        try:
            batch: list[str] = []
            for key in self._client.scan_iter(match=f"{PREFIX}:*", count=500):
                batch.append(key)
                if len(batch) >= 500:
                    removed += int(self._client.delete(*batch))
                    batch.clear()
            if batch:
                removed += int(self._client.delete(*batch))
        except Exception:
            self._local["error"] += 1
        return removed


# 进程级单例：FastAPI 的每个请求共用同一个连接池
cache = Cache()
