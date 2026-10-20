"""账号安全相关的回归测试。

这两个漏洞是代码审查时发现的，都能直接导致**别人接管你的账号**：

1. `/api/reset-password` 原来只校验「用户存在 + 新密码长度」，
   **完全不验证验证码**。任何人 POST 一个用户名就能改掉别人的密码。
2. `/api/send-code` 把验证码直接放在响应里返回，
   等于输入任意用户名就能拿到验证码。

现在：重置必须先在 `/verify-code` 拿到短时凭证，且凭证一次性使用；
验证码回显只在非生产环境开启。这组用例把它们钉住。
"""

import pytest

from app import security


# ============================================================
# 重置密码必须有验证码凭证
# ============================================================

def test_reset_without_verify_is_rejected(client, registered_user):
    """没走验证码流程，直接改密码必须被拒绝（原来的账号接管漏洞）。"""
    resp = client.post(
        "/api/reset-password",
        json={"username": registered_user["username"], "new_password": "hacked123"},
    )
    assert resp.status_code == 400
    assert "验证" in resp.json()["detail"]

    # 原密码必须还能登录
    login = client.post("/api/login", json=registered_user)
    assert login.status_code == 200


def test_reset_after_verify_succeeds(client, registered_user):
    username = registered_user["username"]

    sent = client.post("/api/send-code", json={"username": username})
    assert sent.status_code == 200
    code = sent.json()["code"]

    assert client.post(
        "/api/verify-code", json={"username": username, "code": code}
    ).status_code == 200

    reset = client.post(
        "/api/reset-password",
        json={"username": username, "new_password": "brandnew123"},
    )
    assert reset.status_code == 200

    # 新密码能登录，旧密码不能
    assert client.post(
        "/api/login", json={"username": username, "password": "brandnew123"}
    ).status_code == 200
    assert client.post("/api/login", json=registered_user).status_code == 400


def test_reset_ticket_is_single_use(client, registered_user):
    """改完一次密码，凭证立即失效，不能反复改。"""
    username = registered_user["username"]
    code = client.post("/api/send-code", json={"username": username}).json()["code"]
    client.post("/api/verify-code", json={"username": username, "code": code})

    first = client.post(
        "/api/reset-password", json={"username": username, "new_password": "first123"}
    )
    assert first.status_code == 200

    second = client.post(
        "/api/reset-password", json={"username": username, "new_password": "second123"}
    )
    assert second.status_code == 400


def test_wrong_code_does_not_issue_ticket(client, registered_user):
    username = registered_user["username"]
    client.post("/api/send-code", json={"username": username})

    bad = client.post(
        "/api/verify-code", json={"username": username, "code": "000000"}
    )
    assert bad.status_code == 400

    resp = client.post(
        "/api/reset-password", json={"username": username, "new_password": "whatever1"}
    )
    assert resp.status_code == 400


def test_expired_reset_ticket_is_rejected(client, registered_user, monkeypatch):
    """凭证过期后同样不能改密码。"""
    username = registered_user["username"]
    code = client.post("/api/send-code", json={"username": username}).json()["code"]
    client.post("/api/verify-code", json={"username": username, "code": code})

    from app.routes import auth as auth_module
    # 把凭证改成已过期
    auth_module.reset_tickets[username] = 0

    resp = client.post(
        "/api/reset-password", json={"username": username, "new_password": "expired123"}
    )
    assert resp.status_code == 400


def test_reset_requires_min_length(client, registered_user):
    username = registered_user["username"]
    code = client.post("/api/send-code", json={"username": username}).json()["code"]
    client.post("/api/verify-code", json={"username": username, "code": code})

    resp = client.post(
        "/api/reset-password", json={"username": username, "new_password": "123"}
    )
    assert resp.status_code == 400


# ============================================================
# 验证码回显只在非生产环境开启
# ============================================================

def test_code_is_echoed_in_test_env(client, registered_user):
    """测试环境（APP_ENV=testing）为了调试方便会回显验证码。"""
    resp = client.post("/api/send-code", json={"username": registered_user["username"]})
    body = resp.json()
    assert "code" in body and len(body["code"]) == 6


def test_send_code_for_unknown_user_is_400(client):
    resp = client.post("/api/send-code", json={"username": "nobody_here"})
    assert resp.status_code == 400


# ============================================================
# JWT 密钥不能有「生产环境还能用默认值」的兜底
# ============================================================

def test_production_without_secret_fails_fast(monkeypatch):
    """生产环境缺 JWT_SECRET_KEY 必须启动失败，而不是静默用弱密钥。"""
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError) as exc:
        security._load_secret()
    assert "JWT_SECRET_KEY" in str(exc.value)


def test_development_has_fallback(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    assert security._load_secret() == "dev-fallback-secret"


def test_production_with_secret_uses_it(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "a" * 48)
    monkeypatch.setenv("APP_ENV", "production")
    assert security._load_secret() == "a" * 48


# ============================================================
# 密码存储
# ============================================================

def test_password_is_hashed_not_plaintext(client, db, registered_user):
    """注册后库里存的必须是 bcrypt 哈希，不是明文。"""
    from app.models import User

    user = db.query(User).filter(User.username == registered_user["username"]).first()
    assert user.password != registered_user["password"]
    assert user.password.startswith("$2")
