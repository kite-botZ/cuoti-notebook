"""批量导入接口的接口级测试。

前端 `Bank.vue` 的「开始导入」按钮调的就是这个接口：

    POST /api/banks/{bank_id}/questions/import   (multipart/form-data, 字段名 file)

v1 里这个路由**根本不存在**（`importer.py` 写好了但没人调用），
用户点按钮只会拿到 404。这组用例把接口契约钉住：

- 正常文件全部入库，返回 `inserted`；
- 脏文件部分成功，`issues` 能定位到具体行；
- 同一个文件重复导入要幂等（去重拦掉），不能把题库撑成两倍；
- `dry_run=true` 只校验不落库；
- 越权、格式、大小、空文件都要给出明确错误码。
"""

import json

import pytest

from app.models import Question


def make_item(i: int, **overrides) -> dict:
    item = {
        "stem": f"导入测试第 {i} 题：下列说法正确的是？",
        "question_type": "single",
        "options": ["甲", "乙", "丙", "丁"],
        "correct_answer": "B",
        "explanation": "解析",
    }
    item.update(overrides)
    return item


def upload(client, bank_id, headers, items, filename="q.json", **params):
    content = json.dumps(items, ensure_ascii=False).encode("utf-8")
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/banks/{bank_id}/questions/import"
    if query:
        url += f"?{query}"
    return client.post(
        url,
        files={"file": (filename, content, "application/json")},
        headers=headers,
    )


# ============================================================
# 正常路径
# ============================================================

def test_import_all_good(client, auth_headers, created_bank, db):
    bank_id = created_bank["id"]
    resp = upload(client, bank_id, auth_headers, [make_item(i) for i in range(1, 6)])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["inserted"] == 5
    assert body["failed"] == 0
    assert body["success_rate"] == 1.0
    assert "成功 5 条" in body["message"]

    count = db.query(Question).filter(Question.bank_id == bank_id).count()
    assert count == 5


def test_import_partial_success(client, auth_headers, created_bank, db):
    """核心用例：一行坏，其它行必须照样入库。"""
    bank_id = created_bank["id"]
    items = [make_item(i) for i in range(1, 6)]
    items[2]["correct_answer"] = ""          # 第 3 条答案为空
    items[4]["options"] = ["只有一个"]        # 第 5 条选项不足

    resp = upload(client, bank_id, auth_headers, items)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["inserted"] == 3
    assert body["failed"] == 2
    assert body["success_rate"] == pytest.approx(0.6)
    locations = [i["location"] for i in body["issues"]]
    assert "第 3 条" in locations and "第 5 条" in locations

    count = db.query(Question).filter(Question.bank_id == bank_id).count()
    assert count == 3


def test_import_is_idempotent(client, auth_headers, created_bank, db):
    """重复导入同一个文件不能把题库撑成两倍。"""
    bank_id = created_bank["id"]
    items = [make_item(i) for i in range(1, 4)]

    first = upload(client, bank_id, auth_headers, items).json()
    assert first["inserted"] == 3

    second = upload(client, bank_id, auth_headers, items).json()
    assert second["inserted"] == 0
    assert second["duplicate_count"] == 3

    assert db.query(Question).filter(Question.bank_id == bank_id).count() == 3


def test_import_dedupes_within_one_file(client, auth_headers, created_bank, db):
    bank_id = created_bank["id"]
    items = [make_item(1), make_item(1), make_item(2)]
    body = upload(client, bank_id, auth_headers, items).json()

    assert body["inserted"] == 2
    assert body["duplicate_count"] == 1


def test_import_dry_run_writes_nothing(client, auth_headers, created_bank, db):
    bank_id = created_bank["id"]
    items = [make_item(i) for i in range(1, 4)]
    items[1]["stem"] = ""

    body = upload(client, bank_id, auth_headers, items, dry_run="true").json()
    assert body["dry_run"] is True
    assert body["inserted"] == 0
    assert "校验完成" in body["message"]
    assert db.query(Question).filter(Question.bank_id == bank_id).count() == 0


def test_import_accepts_multiple_types(client, auth_headers, created_bank):
    bank_id = created_bank["id"]
    items = [
        make_item(1),
        {"stem": "多选", "question_type": "multiple",
         "options": ["甲", "乙", "丙"], "correct_answer": "AC", "explanation": ""},
        {"stem": "判断", "question_type": "judge",
         "options": [], "correct_answer": "A", "explanation": ""},
        {"stem": "填空", "question_type": "blank",
         "options": [], "correct_answer": "北京", "explanation": ""},
        {"stem": "计算", "question_type": "calc",
         "options": [], "correct_answer": "96", "explanation": ""},
    ]
    body = upload(client, bank_id, auth_headers, items).json()
    assert body["inserted"] == 5, body.get("issues")


# ============================================================
# 错误路径
# ============================================================

def test_import_rejects_unknown_extension(client, auth_headers, created_bank):
    resp = upload(
        client, created_bank["id"], auth_headers, [make_item(1)], filename="q.txt"
    )
    assert resp.status_code == 422
    assert "不支持" in resp.json()["detail"]


def test_import_rejects_empty_file(client, auth_headers, created_bank):
    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions/import",
        files={"file": ("q.json", b"", "application/json")},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "空" in resp.json()["detail"]


def test_import_broken_json_is_422(client, auth_headers, created_bank):
    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions/import",
        files={"file": ("q.json", b"{not json", "application/json")},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_import_requires_login(client, created_bank):
    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions/import",
        files={"file": ("q.json", b"[]", "application/json")},
    )
    assert resp.status_code == 401


def test_import_into_other_users_bank_is_404(client, auth_headers, created_bank):
    """越权保护：换个用户拿别人的 bank_id 导入，必须是 404 而不是 403/200。"""
    other = {"username": "intruder", "password": "intruder123"}
    assert client.post("/api/register", json=other).status_code == 201
    token = client.post("/api/login", json=other).json()["token"]

    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions/import",
        files={"file": ("q.json", json.dumps([make_item(1)]).encode(), "application/json")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ============================================================
# 导入后的缓存一致性
# ============================================================

def test_import_invalidates_cached_list(client, auth_headers, created_bank):
    """导入会改题目内容 → 必须让旧的列表缓存失效。

    先读一次把缓存写进去，再导入，再读——如果还能读到旧结果，
    用户导入完刷新页面会看不到新题（缓存不一致）。
    """
    bank_id = created_bank["id"]
    before = client.get(
        f"/api/banks/{bank_id}/questions?page=1&page_size=20", headers=auth_headers
    )
    assert before.json() == []
    assert before.headers["X-Total-Count"] == "0"

    upload(client, bank_id, auth_headers, [make_item(i) for i in range(1, 4)])

    after = client.get(
        f"/api/banks/{bank_id}/questions?page=1&page_size=20", headers=auth_headers
    )
    assert after.headers["X-Total-Count"] == "3"
    assert len(after.json()) == 3
