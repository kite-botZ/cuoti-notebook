"""JWT 相关配置。

集中放在这里，避免 `auth.py` 和 `banks.py` 各自写一份 `SECRET_KEY`——
两份写法一旦不一致，就会出现「登录签发的 token 在别的接口验不过」这种很难查的问题。
"""

import os

ALGORITHM = "HS256"


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
