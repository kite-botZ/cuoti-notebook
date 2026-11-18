"""JWT 与签名相关配置。

集中放在这里，避免 `auth.py` 和 `banks.py` 各自写一份 `SECRET_KEY`——
两份写法一旦不一致，就会出现「登录签发的 token 在别的接口验不过」这种很难查的问题。
"""

import os
import time

import jwt

ALGORITHM = "HS256"

# token 默认有效期（秒）。README/.env.example 里的 JWT_EXPIRE_SECONDS 同名。
TOKEN_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", "3600"))


def _load_secret() -> str:
    """读取 JWT 签名密钥。

    生产环境（APP_ENV=production）必须显式配置。以前这里是
    `os.getenv("JWT_SECRET_KEY", "dev-fallback-secret")`——**没有环境变量时会静默
    使用一个写死的弱密钥**，任何人都能拿这个公开的默认值伪造任意用户的 token。
    这种"能跑但完全不安全"的默认值是最危险的，所以生产环境直接启动失败，
    把问题暴露在部署阶段，而不是等被人打进来。
    """
    secret = os.getenv("JWT_SECRET_KEY", "").strip()
    if secret:
        return secret

    if os.getenv("APP_ENV", "development") == "production":
        raise RuntimeError(
            "缺少环境变量 JWT_SECRET_KEY。生产环境必须显式配置，"
            "否则任何人都能用默认密钥伪造 token。生成方式：\n"
            '  python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )

    # 开发 / 测试环境兜底，方便本地直接跑起来
    return "dev-fallback-secret"


SECRET_KEY = _load_secret()


# ============================================================
# token 签发
# ============================================================

# `tv`（token version）是这次新加的声明，用来**吊销已签发的 token**。
#
# 之前改密码只是把新的 bcrypt 哈希写进库，旧 token 在过期前（默认 1 小时）
# 依然完全可用——也就是说「密码泄露 → 改密码」并不能把攻击者踢下线，
# 这正是密码修改最核心的作用之一。
#
# 做法：`users.token_version` 存一个整数，签 token 时把它写进 `tv`；
# 校验时和库里的当前值比对，不一致就 401。改密码时把 `token_version + 1`，
# 所有旧 token 立刻失效，不需要黑名单、不需要 Redis。
#
# 代价是**每个鉴权请求多一次主键查询**（`WHERE id = ?` 走 PRIMARY，
# 实测 MySQL 上 0.1~0.2ms）。换来的是真正可撤销的会话，值。
TOKEN_VERSION_CLAIM = "tv"


def create_access_token(
    user_id: int,
    username: str,
    token_version: int,
    expires_seconds: int | None = None,
) -> str:
    """签发 access token。

    必须在 payload 里带上 `tv`：`current_user_id` 现在要求它存在，
    少带的 token 会被判为「登录已失效」，宁可让调用方立刻发现，
    也不要悄悄放行一个不可吊销的 token。
    """
    expire = TOKEN_EXPIRE_SECONDS if expires_seconds is None else expires_seconds
    payload = {
        "id": user_id,
        "username": username,
        TOKEN_VERSION_CLAIM: int(token_version),
        # exp 是标准字段，PyJWT 会自动校验过期时间
        "exp": int(time.time()) + int(expire),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ============================================================
# 图片访问用的 cookie
# ============================================================

# `/uploads/...` 是**静态图片**，`<img src>` 发不出 Authorization 头，
# 所以没法用 Bearer token 保护——这是它一直裸奔的唯一原因。
#
# 解法：登录时额外下发一个同内容的 HttpOnly cookie，浏览器请求图片时
# 会自动带上，`/uploads` 的路由再自己校验这个 cookie。
#
# 为什么不干脆全站用 cookie 鉴权？因为 cookie 会被浏览器自动附带，
# 状态变更接口（POST/PUT/DELETE）一旦接受 cookie 就会引入 CSRF 问题。
# 这里只在**只读的图片 GET** 上认这个 cookie，API 仍然强制 Bearer，
# 攻击者拿到 cookie 也发不出写请求。
MEDIA_COOKIE = "cuoti_media"

# 生产环境走 HTTPS 时才该打开；本地 http 下开 True，浏览器会直接不接受这个 cookie。
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
