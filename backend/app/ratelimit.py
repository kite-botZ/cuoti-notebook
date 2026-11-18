"""进程内滑动窗口限流。

## 为什么之前没有

`/api/login`、`/api/send-code`、`/api/verify-code` 三个接口原来**完全没有限流**：
验证码是 6 位数字，`/verify-code` 不限制尝试次数，理论上可以用脚本把一个
5 分钟有效的验证码爆破出来，然后走 `/reset-password` 接管账号。
登录接口同样可以被在线字典撞库。这两条都不需要什么高深技巧，是最常见的一类
攻击面，所以这里补一个最小可用的限流。

## 为什么不用 Redis

限流必须**在任何依赖都不可用时仍然生效**。项目的 Redis 是可选组件
（`cache.enabled` 为假时整套缓存静默降级），如果限流也挂在 Redis 上，
没装 Redis 的部署就等于没有限流——正好是最需要保护的那种裸部署。
所以这里用进程内的 `dict + deque`，零依赖、零配置、默认开启。

代价（必须写清楚，否则后继维护者会误以为它是分布式限流）：

- **只在单进程内有效**。`uvicorn --workers N` 时每个 worker 各有一份计数，
  实际阈值是 `N × limit`。要真正跨进程需要 Redis/中间件，那是另一个量级的事。
- 进程重启后计数清零。爆破脚本重启不了服务端，所以这不影响防护效果。
- 内存占用随 key 数增长。这里对 key 数量做了硬上限，超了就整体清空
  （宁可短暂放宽，也不要内存无限涨）。

## 为什么测试环境默认关闭

344 条用例共用同一个 `TestClient`，`request.client.host` 恒为 `testclient`，
真实限流会把整个测试套件打成 429。所以 `APP_ENV=testing` 时默认不生效；
需要验证限流本身的用例显式打开（见 `tests/test_auth_hardening.py`），
测完用 `reset()` 清掉桶，不会污染别的用例。
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

_LOCK = threading.Lock()
# {(bucket, key): deque[timestamp, ...]}
_HITS: "dict[tuple[str, str], deque]" = {}
# key 数量上限。超过就整体清空：丢一窗计数比内存涨爆好。
_MAX_KEYS = 20000


def enabled() -> bool:
    """限流是否生效。

    每次调用都重新读环境变量（而不是 import 时算一次）：
    测试里需要 `monkeypatch.setenv` 临时打开，import 时定死就测不了了。
    """
    raw = os.getenv("AUTH_RATE_LIMIT")
    if raw is not None:
        return raw.strip().lower() not in ("0", "false", "no", "off", "")
    return os.getenv("APP_ENV", "development") != "testing"


def client_ip(request: Request) -> str:
    """取调用方 IP。

    部署在 `docker-compose` 里时，后端前面一定有 nginx，`request.client.host`
    会变成 nginx 的容器地址（所有用户共用一个值，按 IP 限流就失效了），
    所以优先读 `X-Forwarded-For` 的第一段（最靠近客户端的那一跳）。

    ⚠️ 这个头是可以伪造的。安全前提是**后端不能直接暴露在公网**
    （compose 里 backend 是 `expose`/内网，只有 nginx 对 8080），
    否则攻击者只要每次换一个 X-Forwarded-For 就绕过按 IP 的限流。
    按用户名的桶不受这个影响，那里仍会拦住爆破。
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def hit(bucket: str, key: str, limit: int, window: float) -> None:
    """记一次并检查阈值；超限抛 429。

    `bucket` 是用途（login / send-code / ...），`key` 是被限的主体
    （用户名、IP …）。两者组合成一个独立的滑动窗口。

    注意抛 429 时**这一次不计入**，所以用户 etc 秒后重试是干净的。
    """
    if not enabled() or limit <= 0 or window <= 0:
        return

    now = time.time()
    ident = (bucket, key)
    with _LOCK:
        if len(_HITS) > _MAX_KEYS:
            _HITS.clear()
        q = _HITS.get(ident)
        if q is None:
            q = _HITS[ident] = deque()
        # 滑掉窗口外的旧记录。deque 天然按时间有序，popleft 即可。
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            retry = max(1, int(window - (now - q[0])) + 1)
            raise HTTPException(
                status_code=429,
                detail=f"操作过于频繁，请 {retry} 秒后再试",
                headers={"Retry-After": str(retry)},
            )
        q.append(now)


def clear(bucket: str, key: str) -> None:
    """清掉某个主体的计数。

    用在"成功即清零"的场景：比如登录成功说明密码是对的，
    之前那几次失败不该继续累计（否则用户偶尔记错几次密码就会被锁）。
    """
    with _LOCK:
        _HITS.pop((bucket, key), None)


def reset() -> None:
    """清空所有计数。测试用。"""
    with _LOCK:
        _HITS.clear()
