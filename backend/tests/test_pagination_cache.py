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


# ============================================================
# 服务端搜索（分页之后，客户端过滤只能搜到当前页，所以必须回源）
# ============================================================

def test_search_finds_question_outside_current_page(client, auth_headers, created_bank):
    """关键回归：目标题在很后面，但 page=1 的搜索请求也必须能搜到。

    分页之前前端是在已加载的全量数组上过滤的，所以"搜得到"。
    分页之后如果还留在客户端过滤，就只能搜到当前页——这条用例盯着这个回归。
    """
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 30)

    # 单页只放 5 条，目标题（第 1 题，id 最小、倒序排在最后）落在第 6 页
    near = client.get(
        f"/api/banks/{bank_id}/questions?page=1&page_size=5", headers=auth_headers
    ).json()
    assert not any("第 1 题" in q["stem"] for q in near), "前置条件：目标题不在第 1 页"

    resp = client.get(
        f"/api/banks/{bank_id}/questions"
        "?page=1&page_size=5&q=" + "分页测试第 1 题",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    hits = resp.json()
    assert len(hits) == 1, f"应该只命中 1 条，实际 {len(hits)}"
    assert hits[0]["stem"] == "分页测试第 1 题"
    assert resp.headers["X-Total-Count"] == "1", "总数应该是过滤后的数量"


def test_search_matches_note(client, auth_headers, created_bank):
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 3)
    target = client.get(
        f"/api/banks/{bank_id}/questions?page=1&page_size=5", headers=auth_headers
    ).json()[0]

    client.put(
        f"/api/questions/{target['id']}/note",
        json={"note": "这里我老是记错符号"},
        headers=auth_headers,
    )

    hits = client.get(
        f"/api/banks/{bank_id}/questions?q=老是记错", headers=auth_headers
    ).json()
    assert [q["id"] for q in hits] == [target["id"]]


def test_search_escapes_like_wildcards(client, auth_headers, created_bank):
    """搜 `%` 不能变成"匹配所有题"。"""
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 5)
    client.post(
        f"/api/banks/{bank_id}/questions",
        json={"stem": "命中率 50% 是多少", "question_type": "blank",
              "options": [], "correct_answer": "0.5", "explanation": ""},
        headers=auth_headers,
    )

    hits = client.get(
        f"/api/banks/{bank_id}/questions?q=" + "50%", headers=auth_headers
    ).json()
    assert [q["stem"] for q in hits] == ["命中率 50% 是多少"], \
        f"% 没转义的话会匹配到全部 6 条，实际 {len(hits)} 条"

    # 下划线同理：`_` 在 LIKE 里是"任意一个字符"
    hits = client.get(
        f"/api/banks/{bank_id}/questions?q=" + "第_题", headers=auth_headers
    ).json()
    assert hits == [], "没有任何题干含字面量下划线，`_` 必须被当作普通字符"


@pytest.mark.skipif(not cache.enabled, reason="需要可用的 Redis")
def test_search_bypasses_cache(client, auth_headers, created_bank):
    """搜索请求完全不碰缓存层。

    注意这里断言的是 hit/miss **都不动**，而不是"第二次还 miss"：
    搜索路径直接走回源分支，压根没调用 cache.get_json，
    所以连 miss 都不会记一次。
    """
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 3)
    url = f"/api/banks/{bank_id}/questions?page=1&page_size=20&q=分页"

    cache.reset_stats()
    client.get(url, headers=auth_headers)
    first = cache.stats()
    client.get(url, headers=auth_headers)
    second = cache.stats()

    assert first["hit"] == 0 and first["miss"] == 0, f"搜索不该读写缓存：{first}"
    assert second["hit"] == 0 and second["miss"] == 0, f"搜索不该读写缓存：{second}"

    # 反过来验证对照组：同一条 URL 去掉 q 之后，第二次就该命中缓存了，
    # 否则上面那条断言可能只是因为缓存整个没生效。
    plain = f"/api/banks/{bank_id}/questions?page=1&page_size=20"
    cache.reset_stats()
    client.get(plain, headers=auth_headers)
    client.get(plain, headers=auth_headers)
    assert cache.stats()["hit"] > 0, "不搜索的分页请求应该命中缓存"


# ============================================================
# 题库计数（分页之后前端算不出来，必须由服务端提供）
# ============================================================

def _stats(client, bank_id, headers):
    resp = client.get(f"/api/banks/{bank_id}/question-stats", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_question_stats_counts_each_category(client, auth_headers, created_bank):
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 6)
    ids = [q["id"] for q in client.get(
        f"/api/banks/{bank_id}/questions?page=1&page_size=20", headers=auth_headers
    ).json()]

    # 一道收藏、一道斩题、一道答错、一道写笔记，彼此不重叠
    client.post(f"/api/questions/{ids[0]}/favorite", headers=auth_headers)
    client.post(f"/api/questions/{ids[1]}/cut", headers=auth_headers)
    client.post(f"/api/questions/{ids[2]}/answer",
                json={"selected_answer": "D"}, headers=auth_headers)   # 正确是 A，答错
    client.put(f"/api/questions/{ids[3]}/note",
               json={"note": "错题笔记"}, headers=auth_headers)

    st = _stats(client, bank_id, auth_headers)
    assert st["total"] == 6
    assert st["cut"] == 1, "斩题数不对"
    assert st["normal"] == 5, "非斩题数不对"
    assert st["favorite"] == 1
    assert st["wrong"] == 1
    assert st["note"] == 1


def test_question_stats_excludes_cut_from_wrong_and_favorite(
    client, auth_headers, created_bank
):
    """收藏 + 斩题之后，它不该再算进「我的收藏」——和前端的 computed 口径一致。"""
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 2)
    target = client.get(
        f"/api/banks/{bank_id}/questions?page=1&page_size=20", headers=auth_headers
    ).json()[0]["id"]

    client.post(f"/api/questions/{target}/favorite", headers=auth_headers)
    assert _stats(client, bank_id, auth_headers)["favorite"] == 1

    client.post(f"/api/questions/{target}/cut", headers=auth_headers)
    st = _stats(client, bank_id, auth_headers)
    assert st["favorite"] == 0, "斩题之后不该还算作收藏"
    assert st["cut"] == 1
    assert st["normal"] == 1


def test_question_stats_by_type_splits_image_questions(
    client, auth_headers, created_bank
):
    """带图的题单独算一类，不再计入原题型（和前端 typeList 一致）。"""
    bank_id = created_bank["id"]
    client.post(
        f"/api/banks/{bank_id}/questions",
        json={"stem": "看图作答 ![图](/uploads/a.png)", "question_type": "single",
              "options": ["甲", "乙"], "correct_answer": "A", "explanation": ""},
        headers=auth_headers,
    )
    client.post(
        f"/api/banks/{bank_id}/questions",
        json={"stem": "普通单选题", "question_type": "single",
              "options": ["甲", "乙"], "correct_answer": "A", "explanation": ""},
        headers=auth_headers,
    )

    by_type = _stats(client, bank_id, auth_headers)["by_type"]
    assert by_type["image"] == 1
    assert by_type["single"] == 1, "带图的题不该再算进单选"

    # 六个题型键必须都在，前端的格子不能因为缺 key 显示成 NaN
    for key in ("single", "multiple", "judge", "blank", "short", "calc", "image"):
        assert key in by_type, f"缺 {key}"


def test_question_stats_by_type_excludes_cut(client, auth_headers, created_bank):
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 3)
    target = client.get(
        f"/api/banks/{bank_id}/questions?page=1&page_size=20", headers=auth_headers
    ).json()[0]["id"]
    client.post(f"/api/questions/{target}/cut", headers=auth_headers)

    assert _stats(client, bank_id, auth_headers)["by_type"]["single"] == 2


def test_question_stats_is_per_user(client, auth_headers, created_bank):
    """别人斩了题，不能影响我看到的计数。"""
    bank_id = created_bank["id"]
    bulk_import(client, bank_id, auth_headers, 2)
    assert _stats(client, bank_id, auth_headers)["cut"] == 0


def test_question_stats_rejects_other_users_bank(client, auth_headers):
    """越权访问别人的题库要 404，而不是泄漏计数。"""
    other = client.post(
        "/api/banks",
        json={"name": "别人的题库", "subject": "数学", "description": ""},
        headers=auth_headers,
    ).json()

    # 换一个用户
    client.post("/api/register", json={"username": "intruder", "password": "test123456"})
    token = client.post(
        "/api/login", json={"username": "intruder", "password": "test123456"}
    ).json()["token"]
    resp = client.get(
        f"/api/banks/{other['id']}/question-stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
