"""用户认证接口测试。

覆盖：
- 注册成功 / 重复注册 / 密码太短 / 字段缺失
- 登录成功 / 密码错误 / 用户不存在
- JWT token 的有效性
"""


def test_register_success(client):
    """正常注册：返回 201，且响应里包含 id 和 username。"""
    resp = client.post("/api/register", json={
        "username": "alice",
        "password": "alice123456",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["username"] == "alice"
    assert "id" in data
    assert data["message"] == "注册成功"


def test_register_duplicate_username(client):
    """重复注册同名用户：第二次返回 400。"""
    payload = {"username": "bob", "password": "bob123456"}

    first = client.post("/api/register", json=payload)
    assert first.status_code == 201

    second = client.post("/api/register", json=payload)
    assert second.status_code == 400
    assert "已存在" in second.json()["detail"]


def test_register_password_too_short(client):
    """密码少于 6 位：拒绝。"""
    resp = client.post("/api/register", json={
        "username": "charlie",
        "password": "123",
    })
    assert resp.status_code in (400, 422)


def test_register_missing_fields(client):
    """缺少字段：FastAPI 自动返回 422。"""
    resp = client.post("/api/register", json={"username": "dave"})
    assert resp.status_code == 422


def test_login_success(client, registered_user):
    """登录成功：返回 token。"""
    resp = client.post("/api/login", json=registered_user)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "token" in data
    assert data["username"] == registered_user["username"]
    # JWT 是三段式（header.payload.signature）
    assert data["token"].count(".") == 2


def test_login_wrong_password(client, registered_user):
    """密码错误：返回 400。"""
    resp = client.post("/api/login", json={
        "username": registered_user["username"],
        "password": "wrong_password",
    })
    assert resp.status_code == 400
    assert "密码" in resp.json()["detail"]


def test_login_user_not_exist(client):
    """用户不存在：返回 400。"""
    resp = client.post("/api/login", json={
        "username": "nobody",
        "password": "123456",
    })
    assert resp.status_code == 400
    assert "不存在" in resp.json()["detail"]


def test_auth_required_for_protected_endpoint(client):
    """访问受保护接口不带 token：应返回 401 或 403。"""
    resp = client.get("/api/banks")
    assert resp.status_code in (401, 403)


def test_auth_with_token(client, auth_headers):
    """带 token 访问受保护接口：应成功。"""
    resp = client.get("/api/banks", headers=auth_headers)
    assert resp.status_code == 200
    # 新用户没有题库，应该返回空数组
    assert resp.json() == []