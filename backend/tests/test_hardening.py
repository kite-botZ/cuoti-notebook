"""账号安全加固的回归测试。

对应 `系统分析.md` 里 P0 缺陷清单的第一组：

1. **改密码 / 重置密码不吊销旧 token** —— 密码泄露后改密码，攻击者手上的
   旧 token 在过期前（默认 1 小时）依然可用，"改密码"这个动作等于没做。
2. **认证接口完全没有限流** —— 6 位验证码可以被脚本穷举，登录可以被撞库。
3. **`/api/practice/progress` 的 GET/DELETE 不校验题库归属** —— 越权面。
4. **`/uploads` 是公开静态目录** —— 无需登录即可读任何图片。

这些用例的作用是：以后谁"顺手简化"掉这些校验，测试会立刻红。
"""

import os

import jwt
import pytest

from app import ratelimit, security

TEST_PASSWORD = "test123456"


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """限流是进程内状态，必须每个用例前后清空，否则用例之间互相污染。

    （测试环境默认不开限流，见 `ratelimit.enabled()`；这里给
    "显式打开限流"的那几条用例兜底。）
    """
    ratelimit.reset()
    yield
    ratelimit.reset()


def _login(client, username: str, password: str = TEST_PASSWORD) -> dict:
    resp = client.post("/api/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _register(client, username: str, password: str = TEST_PASSWORD) -> dict:
    resp = client.post("/api/register", json={"username": username, "password": password})
    assert resp.status_code == 201, resp.text
    return {"username": username, "password": password}


# ============================================================
# 1. token 吊销（token_version）
# ============================================================

def test_change_password_revokes_old_token(client, registered_user):
    """改完密码，旧 token 必须立刻失效，新登录拿到的 token 才能用。"""
    headers = _login(client, registered_user["username"])
    assert client.get("/api/banks", headers=headers).status_code == 200

    changed = client.post(
        "/api/user/change-password",
        json={"old_password": TEST_PASSWORD, "new_password": "brandnew123"},
        headers=headers,
    )
    assert changed.status_code == 200, changed.text

    # 旧 token 被吊销（不是 200，也不能是 500）
    assert client.get("/api/banks", headers=headers).status_code == 401

    # 新密码登录拿到的 token 正常
    fresh = _login(client, registered_user["username"], "brandnew123")
    assert client.get("/api/banks", headers=fresh).status_code == 200


def test_reset_password_revokes_old_token(client, registered_user):
    """走"忘记密码"重置后，旧 token 同样要失效。

    场景很实际：账号被别人登着 → 你重置密码 → 如果旧 token 还能用，
    那个人最多还能再操作一小时。
    """
    headers = _login(client, registered_user["username"])

    code = client.post(
        "/api/send-code", json={"username": registered_user["username"]}
    ).json()["code"]
    assert client.post(
        "/api/verify-code",
        json={"username": registered_user["username"], "code": code},
    ).status_code == 200
    assert client.post(
        "/api/reset-password",
        json={"username": registered_user["username"], "new_password": "reset12345"},
    ).status_code == 200

    assert client.get("/api/banks", headers=headers).status_code == 401


def test_token_without_version_claim_is_rejected(client, registered_user):
    """没有 `tv` 声明的 token 一律不认。

    老版本签发的 token 就是这种形态。放行它们等于给"永不可吊销"留了后门，
    所以这里选择一次性阵痛：升级后所有人都要重新登录一次。
    """
    user_id = client.get(
        "/api/user/me", headers=_login(client, registered_user["username"])
    ).json()["id"]

    legacy = jwt.encode(
        {"id": user_id, "username": registered_user["username"]},
        security.SECRET_KEY,
        algorithm=security.ALGORITHM,
    )
    resp = client.get("/api/banks", headers={"Authorization": f"Bearer {legacy}"})
    assert resp.status_code == 401


def test_token_with_stale_version_is_rejected(client, registered_user, db):
    """`tv` 和库里的值不一致（= 已被吊销）必须 401。"""
    from app.models import User

    headers = _login(client, registered_user["username"])
    token_version = jwt.decode(
        headers["Authorization"].split(" ", 1)[1],
        security.SECRET_KEY,
        algorithms=[security.ALGORITHM],
    )["tv"]

    # 模拟"别处改了密码"：直接把版本号推到下一个
    user = db.query(User).filter(User.username == registered_user["username"]).first()
    user.token_version = token_version + 1
    db.commit()

    assert client.get("/api/banks", headers=headers).status_code == 401


# ============================================================
# 2. 限流
# ============================================================

def test_login_failures_are_limited(client, registered_user, monkeypatch):
    """同一账号连续失败到阈值后返回 429（而不是无限试密码）。"""
    monkeypatch.setenv("AUTH_RATE_LIMIT", "1")

    from app.routes import auth as auth_module

    for _ in range(auth_module.LOGIN_MAX_FAILURES):
        resp = client.post(
            "/api/login",
            json={"username": registered_user["username"], "password": "wrong"},
        )
        assert resp.status_code == 400, resp.text

    blocked = client.post(
        "/api/login",
        json={"username": registered_user["username"], "password": "wrong"},
    )
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers

    # 正确密码仍然放行：限流只锁"猜错的尝试"，不锁人。
    # 这是有意的取舍——如果把整个账号锁死，任何人知道你的用户名就能
    # 用 5 次错密码让你登不进去（拿限流做拒绝服务）。
    # 穷举依然被挡住：错的尝试一律 429，且成功即清零计数。
    assert client.post("/api/login", json=registered_user).status_code == 200


def test_successful_login_clears_failure_counter(client, registered_user, monkeypatch):
    """登录成功要清零失败计数，否则偶尔记错几次密码就会被锁。"""
    monkeypatch.setenv("AUTH_RATE_LIMIT", "1")

    from app.routes import auth as auth_module

    for _ in range(auth_module.LOGIN_MAX_FAILURES - 1):
        client.post(
            "/api/login",
            json={"username": registered_user["username"], "password": "wrong"},
        )
    assert client.post("/api/login", json=registered_user).status_code == 200

    # 计数已清零：再错 MAX-1 次仍然只是 400，不会 429
    for _ in range(auth_module.LOGIN_MAX_FAILURES - 1):
        resp = client.post(
            "/api/login",
            json={"username": registered_user["username"], "password": "wrong"},
        )
        assert resp.status_code == 400


def test_verify_code_is_invalidated_after_too_many_tries(client, registered_user):
    """验证码错到阈值后作废：即使之后猜对了也不能用。

    这是防穷举的关键。原来 `/verify-code` 不限次数，6 位码（1e6 种）
    在 5 分钟窗口里是可以用脚本刷完的。
    """
    from app.routes import auth as auth_module

    username = registered_user["username"]
    code = client.post("/api/send-code", json={"username": username}).json()["code"]

    for _ in range(auth_module.VERIFY_MAX_FAILURES - 1):
        resp = client.post("/api/verify-code", json={"username": username, "code": "000000"})
        assert resp.status_code == 400, resp.text

    over = client.post("/api/verify-code", json={"username": username, "code": "000000"})
    assert over.status_code == 429

    # 验证码已被删除：拿正确的码也救不回来
    after = client.post("/api/verify-code", json={"username": username, "code": code})
    assert after.status_code == 400


def test_rate_limit_allows_normal_usage(client, registered_user):
    """限流不能误伤正常用户：测试环境默认不开启，几次登录都该成功。"""
    for _ in range(3):
        assert client.post("/api/login", json=registered_user).status_code == 200


# ============================================================
# 3. 练习进度归属
# ============================================================

def test_progress_requires_bank_ownership(client, created_bank):
    """拿别人的 bank_id 查/删进度必须 404，而不是"查不到就返回 None"。"""
    owner = _login(client, "testuser")
    other = _register(client, "mallory")
    other_headers = _login(client, other["username"])

    # 别人（mallory）对 testuser 的题库做操作
    assert client.get(
        f"/api/practice/progress?bank_id={created_bank['id']}&source=bank",
        headers=other_headers,
    ).status_code == 404
    assert client.put(
        "/api/practice/progress",
        json={"bank_id": created_bank["id"], "source": "bank", "question_ids": [1]},
        headers=other_headers,
    ).status_code == 404
    assert client.delete(
        f"/api/practice/progress?bank_id={created_bank['id']}&source=bank",
        headers=other_headers,
    ).status_code == 404

    # 所有者自己仍然正常
    ok = client.get(
        f"/api/practice/progress?bank_id={created_bank['id']}&source=bank",
        headers=owner,
    )
    assert ok.status_code == 200
    assert ok.json()["progress"] is None


# ============================================================
# 4. 图片访问鉴权
# ============================================================

@pytest.fixture()
def uploaded_file():
    """在真实的上传目录里放一个测试文件，用完删掉。"""
    import app.main as main_module

    sub = "pytest_tmp"
    directory = os.path.join(main_module.UPLOAD_DIR, sub)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "probe.png")
    with open(path, "wb") as f:
        # 1x1 的透明 PNG
        f.write(bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
        ))
    try:
        yield f"/uploads/{sub}/probe.png", path
    finally:
        try:
            os.remove(path)
            os.rmdir(directory)
        except OSError:
            pass


def test_upload_requires_login_when_enforcing(client, auth_headers, uploaded_file, monkeypatch):
    """生产口径（UPLOAD_REQUIRE_AUTH=True）：没登录读图片 401，登录后 200。"""
    import app.main as main_module

    monkeypatch.setattr(main_module, "UPLOAD_REQUIRE_AUTH", True)
    url, _ = uploaded_file

    # 清掉登录留下的 cookie，模拟"匿名访客直接拿链接访问"
    client.cookies.clear()
    assert client.get(url).status_code == 401

    # 带 Bearer 头可以读
    assert client.get(url, headers=auth_headers).status_code == 200


def test_upload_readable_with_media_cookie(client, registered_user, uploaded_file, monkeypatch):
    """`<img src>` 发不出 Authorization 头，靠登录时下发的 HttpOnly cookie 鉴权。"""
    import app.main as main_module

    monkeypatch.setattr(main_module, "UPLOAD_REQUIRE_AUTH", True)
    url, _ = uploaded_file

    login = client.post("/api/login", json=registered_user)
    assert login.status_code == 200
    assert security.MEDIA_COOKIE in client.cookies

    assert client.get(url).status_code == 200


def test_upload_open_in_development(client, uploaded_file, monkeypatch):
    """开发口径（UPLOAD_REQUIRE_AUTH=False）：保持原行为，避免本地数据全裂图。"""
    import app.main as main_module

    monkeypatch.setattr(main_module, "UPLOAD_REQUIRE_AUTH", False)
    client.cookies.clear()
    url, _ = uploaded_file
    assert client.get(url).status_code == 200


def test_upload_blocks_path_traversal(client, uploaded_file, monkeypatch):
    """`..` 不能穿出上传目录（静态挂载时代由 Starlette 兜着，换成显式路由后要自己挡）。"""
    import app.main as main_module

    monkeypatch.setattr(main_module, "UPLOAD_REQUIRE_AUTH", False)
    client.cookies.clear()

    resp = client.get("/uploads/%2E%2E/app/main.py")
    assert resp.status_code == 404


def test_upload_missing_file_is_404(client, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "UPLOAD_REQUIRE_AUTH", False)
    client.cookies.clear()
    assert client.get("/uploads/pytest_tmp/not-exists.png").status_code == 404
