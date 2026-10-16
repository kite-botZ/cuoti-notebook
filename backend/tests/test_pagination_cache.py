"""分页、缓存与缓存一致性的测试。

这组用例是导师那几句追问的可验证答案：

- 「题库检索慢，你设计了什么机制，响应时间从多少降到多少」→ 分页 + 缓存
- 「补充 redis 跟缓存的一致性，至少做一个缓存场景」→ 写后版本号失效
- 「批量斩题」的 N+1 修复 → 状态批量写入后结果依然正确
"""

import json

import pytest

from app.cache import cache
from app.models import AnswerAttempt, Question, QuestionUserState

pytestmark = pytest.mark.usefixtures("client")


def bulk_import(client, bank_id, headers, count: int):
    items = [
        {
            "stem": f"分页测试第 {i} 题",
            "question_type": "single",
            "options": ["甲", "乙", "丙", "丁"],
            "correct_answer": "A",
            "explanation": "",
        }
        for i in range(1, count + 1)
    ]
    resp = client.post(
        f"/api/banks/{bank_id}/questions/import",
        files={"file": ("q.json", json.dumps(items, ensure_ascii=False).encode(), "application/json")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ============================================================
# 分页契约
# ============================================================

def test_pagination_headers(client, auth_headers, created_bank):
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 5)

    resp = client.get(
        f"/api/banks/{bank_id}/questions?page=1&page_size=2", headers=auth_headers
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2
    assert resp.headers["X-Total-Count"] == "5"
    assert resp.headers["X-Page"] == "1"
    assert resp.headers["X-Page-Size"] == "2"
    assert resp.headers["X-Has-More"] == "true"


def test_pagination_last_page(client, auth_headers, created_bank):
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 5)

    resp = client.get(
        f"/api/banks/{bank_id}/questions?page=3&page_size=2", headers=auth_headers
    )
    assert len(resp.json()) == 1
    assert resp.headers["X-Has-More"] == "false"


def test_pagination_no_overlap_between_pages(client, auth_headers, created_bank):
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 6)

    p1 = [q["id"] for q in client.get(
        f"/api/banks/{bank_id}/questions?page=1&page_size=3", headers=auth_headers).json()]
    p2 = [q["id"] for q in client.get(
        f"/api/banks/{bank_id}/questions?page=2&page_size=3", headers=auth_headers).json()]
    assert len(p1) == 3 and len(p2) == 3
    assert not set(p1) & set(p2), "两页之间不能有重复题目"


def test_no_page_param_keeps_v1_behaviour(client, auth_headers, created_bank):
    """不传 page 时保持返回全量（老前端兼容）。"""
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 7)

    resp = client.get(f"/api/banks/{bank_id}/questions", headers=auth_headers)
    assert len(resp.json()) == 7
    assert resp.headers["X-Page-Size"] == "7"


def test_page_must_be_positive(client, auth_headers, created_bank):
    resp = client.get(
        f"/api/banks/{created_bank['id']}/questions?page=0", headers=auth_headers
    )
    assert resp.status_code == 422


def test_page_size_is_capped(client, auth_headers, created_bank):
    """page_size 上限 100，防止有人用 page_size=1000000 打接口。"""
    resp = client.get(
        f"/api/banks/{created_bank['id']}/questions?page=1&page_size=100000",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.headers["X-Page-Size"] == "100"


# ============================================================
# 缓存命中
# ============================================================

@pytest.mark.skipif(not cache.enabled, reason="需要可用的 Redis")
def test_second_page_request_hits_cache(client, auth_headers, created_bank):
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 3)
    url = f"/api/banks/{bank_id}/questions?page=1&page_size=20"

    cache.reset_stats()
    client.get(url, headers=auth_headers)          # 第一次：回源
    first = cache.stats()
    client.get(url, headers=auth_headers)          # 第二次：命中
    second = cache.stats()

    assert second["hit"] > first["hit"], "第二次请求应该命中缓存"
    assert second["miss"] == first["miss"], "第二次不应该再回源"


@pytest.mark.skipif(not cache.enabled, reason="需要可用的 Redis")
def test_cache_stats_endpoint(client):
    resp = client.get("/api/cache/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert "hit_rate" in body


# ============================================================
# 缓存一致性：写路径必须让旧缓存失效
# ============================================================

def test_update_question_invalidates_cache(client, auth_headers, created_bank):
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 2)
    url = f"/api/banks/{bank_id}/questions?page=1&page_size=20"

    first = client.get(url, headers=auth_headers).json()
    target = first[0]

    new_stem = "改过之后的题干"
    resp = client.put(
        f"/api/questions/{target['id']}",
        json={"stem": new_stem},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    after = {q["id"]: q["stem"] for q in client.get(url, headers=auth_headers).json()}
    assert after[target["id"]] == new_stem, "改了题干之后不能再读到旧缓存"


def test_delete_question_invalidates_cache(client, auth_headers, created_bank):
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 3)
    url = f"/api/banks/{bank_id}/questions?page=1&page_size=20"

    before = client.get(url, headers=auth_headers).json()
    victim = before[0]["id"]

    assert client.delete(f"/api/questions/{victim}", headers=auth_headers).status_code == 200

    after = client.get(url, headers=auth_headers).json()
    assert victim not in [q["id"] for q in after]
    assert len(after) == 2


def test_create_question_invalidates_cache(client, auth_headers, created_bank):
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 2)
    url = f"/api/banks/{bank_id}/questions?page=1&page_size=20"

    assert len(client.get(url, headers=auth_headers).json()) == 2
    client.post(
        f"/api/banks/{bank_id}/questions",
        json={"stem": "新增的题", "question_type": "single",
              "options": ["甲", "乙"], "correct_answer": "A", "explanation": ""},
        headers=auth_headers,
    )
    assert len(client.get(url, headers=auth_headers).json()) == 3


def test_user_state_change_is_not_cached(client, auth_headers, created_bank, sample_question):
    """用户状态（收藏）不缓存，收藏后立刻读列表必须能看到。"""
    bank_id = created_bank["id"]
    url = f"/api/banks/{bank_id}/questions?page=1&page_size=20"

    first = client.get(url, headers=auth_headers).json()
    assert first[0]["is_favorite"] is False

    assert client.post(
        f"/api/questions/{sample_question['id']}/favorite", headers=auth_headers
    ).status_code == 200

    after = client.get(url, headers=auth_headers).json()
    assert after[0]["is_favorite"] is True, "收藏状态不能走缓存"


# ============================================================
# 批量斩题：N+1 修复后结果仍然正确
# ============================================================

def test_batch_cut_creates_states_for_all(client, auth_headers, created_bank, db):
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 5)
    ids = [q["id"] for q in client.get(
        f"/api/banks/{bank_id}/questions", headers=auth_headers).json()]

    resp = client.post(
        f"/api/banks/{bank_id}/questions/batch-cut",
        json={"question_ids": ids, "is_cut": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 5

    # 5 条状态必须都建出来了，且只有一个事务里提交
    assert db.query(QuestionUserState).count() == 5
    cut_list = client.get(
        f"/api/banks/{bank_id}/questions?filter_type=cut", headers=auth_headers
    ).json()
    assert len(cut_list) == 5
    assert "correct_answer" in cut_list[0]      # 斩题列表要带答案


def test_batch_cut_reuses_existing_state(client, auth_headers, created_bank, sample_question, db):
    """已经收藏过的题再批量斩题，不能插出第二条状态（联合唯一约束）。"""
    bank_id = created_bank["id"]
    qid = sample_question["id"]
    client.post(f"/api/questions/{qid}/favorite", headers=auth_headers)

    resp = client.post(
        f"/api/banks/{bank_id}/questions/batch-cut",
        json={"question_ids": [qid], "is_cut": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert db.query(QuestionUserState).count() == 1
    state = db.query(QuestionUserState).first()
    assert state.is_favorite is True and state.is_cut is True


# ============================================================
# 回归：列类型缺陷
# ============================================================

def test_answer_attempt_selected_answer_is_text():
    """回归用例：selected_answer 曾经被声明成 Integer。

    SQLite 是弱类型，把 "AB" 塞进 INTEGER 列也不报错，所以 44 个老用例
    全绿；但 MySQL 严格模式下会直接 1366 Incorrect integer value。
    这里断言列类型，保证不会再退回 Integer。
    """
    col_type = AnswerAttempt.__table__.c.selected_answer.type
    assert "VARCHAR" in str(col_type).upper()


def test_multiple_choice_answer_is_stored_verbatim(client, auth_headers, created_bank, db):
    """多选题答案是 "AB" 这种字符串，必须原样存取。"""
    bank_id = created_bank["id"]
    resp = client.post(
        f"/api/banks/{bank_id}/questions",
        json={"stem": "多选题", "question_type": "multiple",
              "options": ["甲", "乙", "丙"], "correct_answer": "AC", "explanation": ""},
        headers=auth_headers,
    )
    qid = resp.json()["id"]

    ans = client.post(
        f"/api/questions/{qid}/answer",
        json={"selected_answer": "CA"},           # 顺序无关
        headers=auth_headers,
    )
    assert ans.json()["correct"] is True

    attempt = db.query(AnswerAttempt).filter(AnswerAttempt.question_id == qid).first()
    assert db.query(AnswerAttempt).count() == 1
    assert attempt.selected_answer == "CA"
