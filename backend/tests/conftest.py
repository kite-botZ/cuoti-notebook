"""pytest 全局配置。

关键点：
1. 在 import app 之前设置 APP_ENV=testing，让 db.py 切换到 SQLite 内存库
2. 每个测试用例：跑前建表，跑后清空
3. 提供已注册用户 / 已登录客户端的 fixture，供测试复用
"""

import os

# ⚠️ 必须放在 import app 之前！
os.environ["APP_ENV"] = "testing"
# 测试一律走 ollama 分支：涉及模型调用的用例都是 patch `ollama.Client`，
# 如果继承了开发机 backend/.env 里的 LLM_PROVIDER=bailian，
# 就会绕过 mock 去连真实云端（没配 key 时直接 9 个用例报 LLMError）。
# load_dotenv() 默认不覆盖已存在的环境变量，所以在这里钉住就够了。
os.environ["LLM_PROVIDER"] = "ollama"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-pytest-at-least-32-bytes-long"

import pytest
from fastapi.testclient import TestClient

from app.cache import cache
from app.db import Base, SessionLocal, engine, get_db
from app.main import app


@pytest.fixture(autouse=True)
def clean_cache():
    """每个用例跑之前清掉缓存命名空间。

    缓存是**跨用例共享的外部状态**：SQLite 内存库每个用例都会重建，
    但 Redis 里的 key 不会。如果不管，上一个用例缓存的"题库只有 2 道题"
    会被下一个用例读到，测试就会随机失败——这类 flaky 测试比没有测试更糟。
    """
    cache.clear_namespace()
    cache.reset_stats()
    yield
    cache.clear_namespace()


@pytest.fixture(scope="function")
def db():
    """每个测试用全新的数据库状态。"""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    """FastAPI 的测试客户端，使用测试数据库。"""
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def registered_user(client):
    """注册一个测试用户，返回用户名密码。"""
    user = {"username": "testuser", "password": "test123456"}
    resp = client.post("/api/register", json=user)
    assert resp.status_code == 201, f"注册失败：{resp.text}"
    return user


@pytest.fixture
def auth_headers(client, registered_user):
    """登录并返回 Authorization 头。"""
    resp = client.post("/api/login", json=registered_user)
    assert resp.status_code == 200, f"登录失败：{resp.text}"
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def created_bank(client, auth_headers):
    """创建一个题库，返回它的完整信息。

    用途：很多测试（题目 CRUD、答题、统计）都需要"已有一个题库"，
    用这个 fixture 避免每个测试重复创建。
    """
    resp = client.post(
        "/api/banks",
        json={
            "name": "测试题库",
            "subject": "数学",
            "description": "用于测试",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, f"创建题库失败：{resp.text}"
    return resp.json()

@pytest.fixture
def sample_question(client, auth_headers, created_bank):
    """在测试题库里创建一道单选题，返回它的 id 和内容。

    用途：答题测试、错题本测试都需要"已有一道题"。
    """
    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "1 + 1 等于几？",
            "question_type": "single",
            "options": ["1", "2", "3", "4"],
            "correct_answer": "B",
            "explanation": "1 + 1 = 2",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, f"创建题目失败：{resp.text}"
    return {
        **resp.json(),
        "bank_id": created_bank["id"],
        "correct_answer": "B",  # 测试里知道正确答案
    }