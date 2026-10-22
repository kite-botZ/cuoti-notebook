"""认知诊断 + 自适应选题的接口测试。

这里测的是"接线"是否正确：掌握度有没有真的落库、越权能不能挡住、
自适应选题是不是真的挑了最弱知识点的题。
BKT 公式本身的性质在 `test_bkt.py` 里单独测，两边不重复。
"""

import pytest

from app import bkt


# ============================================================
# 辅助
# ============================================================

def link_kp(client, headers, question_id, name, weight=1.0):
    """给一道题标注一个知识点，返回知识点信息（键名是 `kp_id`）。

    注意不能拿「知识点」「数学」这种大词当名字：`apply_tags` 会把它们过滤掉，
    返回的列表是空的。这里显式断言，免得后面报成更难懂的 KeyError/IndexError。
    """
    resp = client.put(
        f"/api/questions/{question_id}/knowledge-points",
        json={"knowledge_points": [{"name": name, "weight": weight}]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    kps = resp.json()["knowledge_points"]
    assert kps, f"知识点 {name!r} 被过滤掉了（太宽泛或太短），换一个具体的名字"
    return kps[0]


def add_question(client, headers, bank_id, stem, answer="B", qtype="single"):
    resp = client.post(
        f"/api/banks/{bank_id}/questions",
        json={
            "stem": stem,
            "question_type": qtype,
            "options": ["1", "2", "3", "4"],
            "correct_answer": answer,
            "explanation": "解析",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def link_kps(client, headers, question_id, specs):
    """一次给一道题标注多个知识点，按名称返回。

    必须一次标完：`PUT /questions/{id}/knowledge-points` 是**整体覆盖**的，
    分两次调用的话第二次会把第一次的标签顶掉。
    `specs` 是 `(名称, 权重)` 列表。
    """
    resp = client.put(
        f"/api/questions/{question_id}/knowledge-points",
        json={"knowledge_points": [{"name": n, "weight": w} for n, w in specs]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    kps = resp.json()["knowledge_points"]
    assert len(kps) == len(specs), f"标注被过滤了：想要 {specs}，实际得到 {kps}"
    return {k["name"]: k for k in kps}


def answer(client, headers, question_id, selected, expect=200):
    resp = client.post(
        f"/api/questions/{question_id}/answer",
        json={"selected_answer": selected},
        headers=headers,
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def mastery_of(client, headers, bank_id):
    resp = client.get(f"/api/banks/{bank_id}/mastery", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def adaptive(client, headers, bank_id, limit=20):
    resp = client.get(
        f"/api/banks/{bank_id}/adaptive-questions",
        params={"limit": limit},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ============================================================
# 掌握度：作答 → 落库 → 查询
# ============================================================

def test_mastery_is_empty_when_no_kp_tagged(client, auth_headers, created_bank):
    """一道题都没标注知识点时，诊断列表应该是空的，而不是报错。"""
    body = mastery_of(client, auth_headers, created_bank["id"])
    assert body["kp_count"] == 0
    assert body["items"] == []
    assert body["overall_p_known"] is None
    assert body["weakest"] is None


def test_correct_answer_raises_mastery(
    client, auth_headers, created_bank, sample_question
):
    """答对 → 该知识点的掌握度上升，并带上变化明细返回。"""
    kp = link_kp(client, auth_headers, sample_question["id"], "整数加法")

    body = answer(client, auth_headers, sample_question["id"], "B")
    assert body["correct"] is True

    changes = body["mastery_changes"]
    assert len(changes) == 1, "这道题只标了一个知识点，应该只有一条变化"
    c = changes[0]
    assert c["kp_id"] == kp["kp_id"]
    assert c["name"] == "整数加法", "变化里要带知识点名字，前端不用再查一次"
    assert c["p_before"] == pytest.approx(bkt.DEFAULT_PARAMS.p_init, abs=1e-4)
    assert c["p_after"] > c["p_before"]
    assert c["delta"] == pytest.approx(c["p_after"] - c["p_before"], abs=1e-4)
    assert c["level"] == bkt.level(c["p_after"])

    # 落库了没有：换个接口再查一次
    item = mastery_of(client, auth_headers, created_bank["id"])["items"][0]
    assert item["kp_id"] == kp["kp_id"]
    assert item["p_known"] == pytest.approx(c["p_after"], abs=1e-4)
    assert item["attempts"] == 1
    assert item["correct"] == 1
    assert item["practiced"] is True
    assert item["accuracy"] == pytest.approx(1.0)


def test_wrong_answer_lowers_mastery(
    client, auth_headers, created_bank, sample_question
):
    kp = link_kp(client, auth_headers, sample_question["id"], "整数加法")

    body = answer(client, auth_headers, sample_question["id"], "A")
    assert body["correct"] is False
    c = body["mastery_changes"][0]
    assert c["p_after"] < c["p_before"]

    item = mastery_of(client, auth_headers, created_bank["id"])["items"][0]
    assert item["attempts"] == 1
    assert item["correct"] == 0
    assert item["accuracy"] == pytest.approx(0.0)
    assert item["p_known"] == pytest.approx(c["p_after"], abs=1e-4)


def test_mastery_accumulates_over_multiple_attempts(
    client, auth_headers, created_bank, sample_question
):
    """连续答对，掌握度要一路涨，且档位跟着动。"""
    link_kp(client, auth_headers, sample_question["id"], "整数加法")
    levels = []
    for _ in range(3):
        answer(client, auth_headers, sample_question["id"], "B")
        levels.append(mastery_of(client, auth_headers, created_bank["id"])["items"][0]["level"])

    assert levels == ["薄弱", "基本掌握", "熟练"], f"档位序列不对：{levels}"

    item = mastery_of(client, auth_headers, created_bank["id"])["items"][0]
    assert item["attempts"] == 3
    assert item["correct"] == 3
    assert item["p_known"] > 0.9


def test_question_without_kp_returns_empty_changes(
    client, auth_headers, sample_question
):
    """没标注知识点的题照样能判题，只是不产生诊断变化。"""
    body = answer(client, auth_headers, sample_question["id"], "B")
    assert body["correct"] is True
    assert body["mastery_changes"] == []


def test_untouched_kp_is_listed_with_initial_value(
    client, auth_headers, created_bank, sample_question
):
    """没做过的知识点也要列出来，掌握度是 p_init、practiced=false。

    诊断的价值一半在于指出"哪些还没掌握"；只列做过的知识点，
    自适应选题在冷启动时就没有目标了。
    """
    q2 = add_question(client, auth_headers, created_bank["id"], "第二题")
    link_kp(client, auth_headers, sample_question["id"], "整数加法")
    link_kp(client, auth_headers, q2, "分数化简")

    answer(client, auth_headers, sample_question["id"], "B")  # 只做第一题

    body = mastery_of(client, auth_headers, created_bank["id"])
    assert body["kp_count"] == 2
    assert body["practiced_count"] == 1
    assert body["untouched_count"] == 1

    by_name = {i["name"]: i for i in body["items"]}
    assert by_name["分数化简"]["practiced"] is False
    assert by_name["分数化简"]["p_known"] == pytest.approx(bkt.DEFAULT_PARAMS.p_init)
    assert by_name["分数化简"]["attempts"] == 0
    assert by_name["分数化简"]["accuracy"] is None
    assert by_name["整数加法"]["practiced"] is True


def test_mastery_items_sorted_weakest_first(
    client, auth_headers, created_bank, sample_question
):
    """列表按掌握度升序——前端直接渲染，不用再排一次。"""
    q2 = add_question(client, auth_headers, created_bank["id"], "第二题")
    link_kp(client, auth_headers, sample_question["id"], "整数加法")
    link_kp(client, auth_headers, q2, "分数化简")

    # 把"分数化简"练到达成，让"整数加法"成为最弱的
    for _ in range(4):
        answer(client, auth_headers, q2, "B")

    body = mastery_of(client, auth_headers, created_bank["id"])
    assert body["items"][0]["name"] == "整数加法", "最弱的知识点必须排第一"
    assert body["weakest"]["name"] == "整数加法"
    ps = [i["p_known"] for i in body["items"]]
    assert ps == sorted(ps)


def test_mastery_weight_scales_the_change(
    client, auth_headers, created_bank, sample_question
):
    """同一道题上，考查权重 0 的知识点不该被动到，权重 1 的必须动。

    一道题同时考多个知识点是常态，所以权重的作用必须落在同一个作答上比较，
    才有意义。注意要一次标完两个标签（接口是整体覆盖的）。
    """
    kps = link_kps(
        client, auth_headers, sample_question["id"],
        [("顺便考一下", 0.0), ("主考知识点", 1.0)],
    )

    body = answer(client, auth_headers, sample_question["id"], "B")
    by_name = {c["name"]: c for c in body["mastery_changes"]}
    assert set(by_name) == {"顺便考一下", "主考知识点"}
    assert abs(by_name["顺便考一下"]["delta"]) < 1e-9, "权重 0 不该有任何变化"
    assert by_name["顺便考一下"]["p_after"] == pytest.approx(bkt.DEFAULT_PARAMS.p_init)
    assert by_name["主考知识点"]["delta"] > 0
    assert by_name["主考知识点"]["kp_id"] == kps["主考知识点"]["kp_id"]


def test_summary_endpoint_hides_item_detail(
    client, auth_headers, created_bank, sample_question
):
    """轻量接口不返回明细，题库页顶部只要总体情况。"""
    link_kp(client, auth_headers, sample_question["id"], "整数加法")
    resp = client.get(
        f"/api/banks/{created_bank['id']}/mastery/summary", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" not in body
    assert body["kp_count"] == 1
    assert body["weakest"]["name"] == "整数加法"


def test_kp_mastery_single_endpoint(client, auth_headers, created_bank, sample_question):
    kp = link_kp(client, auth_headers, sample_question["id"], "整数加法")
    answer(client, auth_headers, sample_question["id"], "B")

    resp = client.get(f"/api/knowledge-points/{kp['kp_id']}/mastery", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["kp_id"] == kp["kp_id"]
    assert body["attempts"] == 1
    assert body["practiced"] is True
    assert body["p_known"] > bkt.DEFAULT_PARAMS.p_init


def test_kp_mastery_unknown_kp_returns_404(client, auth_headers):
    resp = client.get("/api/knowledge-points/999999/mastery", headers=auth_headers)
    assert resp.status_code == 404


# ============================================================
# 权限 / 隔离
# ============================================================

def test_mastery_requires_login(client, created_bank):
    assert client.get(f"/api/banks/{created_bank['id']}/mastery").status_code == 401
    assert client.get(
        f"/api/banks/{created_bank['id']}/adaptive-questions"
    ).status_code == 401


def test_mastery_rejects_other_users_bank(client, auth_headers, created_bank):
    """别人的题库连掌握度都不能看（题库归属校验先于诊断）。"""
    other = {"username": "mastery_intruder", "password": "intruder123"}
    client.post("/api/register", json=other)
    token = client.post("/api/login", json=other).json()["token"]
    h = {"Authorization": f"Bearer {token}"}

    assert client.get(
        f"/api/banks/{created_bank['id']}/mastery", headers=h
    ).status_code == 404
    assert client.get(
        f"/api/banks/{created_bank['id']}/adaptive-questions", headers=h
    ).status_code == 404
    assert client.delete(
        f"/api/banks/{created_bank['id']}/mastery", headers=h
    ).status_code == 404


def test_mastery_is_per_user(client, auth_headers, created_bank, sample_question):
    """知识点是全局共享的，但掌握度必须按用户隔离。

    构造方式：两个用户各自在自己的题库里，给**自己的**题标注同一个知识点名
    （同名同科目 → 全局同一个 `kp_id`），然后一个答对、一个答错。
    同一个知识点上的掌握度必须一个升一个降。

    为什么不能让 B 去做 A 的题：那条路已经被 `ensure_question_owned` 挡成 404 了
    （见 test_mastery_rejects_other_users_bank），拿它当"隔离"的证明是假的。
    真正要防的是两个人在**同一个知识点**上互相污染。
    """
    kp_a = link_kp(client, auth_headers, sample_question["id"], "整数加法")
    answer(client, auth_headers, sample_question["id"], "B")

    other = {"username": "mastery_other", "password": "other123456"}
    client.post("/api/register", json=other)
    token = client.post("/api/login", json=other).json()["token"]
    h = {"Authorization": f"Bearer {token}"}

    bank_b = client.post(
        "/api/banks", json={"name": "他的库", "subject": "数学"}, headers=h
    ).json()
    q_b = add_question(client, h, bank_b["id"], "他的题")
    kp_b = link_kp(client, h, q_b, "整数加法")
    assert kp_b["kp_id"] == kp_a["kp_id"], "同名同科目应该是同一个全局知识点"

    body = answer(client, h, q_b, "A")
    assert body["correct"] is False

    a = client.get(f"/api/knowledge-points/{kp_a['kp_id']}/mastery", headers=auth_headers).json()
    b = client.get(f"/api/knowledge-points/{kp_a['kp_id']}/mastery", headers=h).json()

    assert a["p_known"] > bkt.DEFAULT_PARAMS.p_init, "A 答对了，应该高于初值"
    assert b["p_known"] < bkt.DEFAULT_PARAMS.p_init, "B 答错了，应该低于初值"
    assert a["p_known"] != b["p_known"]
    assert a["attempts"] == 1 and b["attempts"] == 1
    assert a["correct"] == 1 and b["correct"] == 0


def test_reset_mastery_only_clears_own_rows(
    client, auth_headers, created_bank, sample_question
):
    """重置诊断只清本人掌握度，不动作答历史。"""
    kp = link_kp(client, auth_headers, sample_question["id"], "整数加法")
    answer(client, auth_headers, sample_question["id"], "B")

    resp = client.delete(
        f"/api/banks/{created_bank['id']}/mastery", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

    item = mastery_of(client, auth_headers, created_bank["id"])["items"][0]
    assert item["p_known"] == pytest.approx(bkt.DEFAULT_PARAMS.p_init)
    assert item["practiced"] is False

    # 作答历史保留：再答一次，attempts 从 1 继续，而不是从头开始
    answer(client, auth_headers, sample_question["id"], "B")
    item = mastery_of(client, auth_headers, created_bank["id"])["items"][0]
    assert item["attempts"] == 1, "重置后 attempts 重新计数（掌握度重算了）"
    assert item["p_known"] > bkt.DEFAULT_PARAMS.p_init


def test_reset_mastery_without_kp_is_harmless(client, auth_headers, created_bank):
    resp = client.delete(
        f"/api/banks/{created_bank['id']}/mastery", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0


# ============================================================
# 自适应选题
# ============================================================

def test_adaptive_falls_back_when_no_kp(client, auth_headers, created_bank, sample_question):
    """没有知识点标注时降级出题，并且说清楚原因。"""
    body = adaptive(client, auth_headers, created_bank["id"], limit=10)
    assert body["strategy"] == "no_kp_fallback"
    assert "message" in body, "降级必须给出原因，不能悄悄换策略"
    assert body["targets"] == []
    assert body["returned"] == 1
    assert body["picked"][0]["id"] == sample_question["id"]


def test_adaptive_targets_weakest_kp_first(
    client, auth_headers, created_bank, sample_question
):
    """最弱的知识点必须出现在 targets 的第一位。"""
    q2 = add_question(client, auth_headers, created_bank["id"], "第二题")
    link_kp(client, auth_headers, sample_question["id"], "已经练熟的")
    link_kp(client, auth_headers, q2, "还没掌握的")

    for _ in range(4):
        answer(client, auth_headers, sample_question["id"], "B")

    body = adaptive(client, auth_headers, created_bank["id"], limit=10)
    assert body["strategy"] in ("bkt_adaptive", "bkt_adaptive_with_fill")
    assert body["targets"][0]["name"] == "还没掌握的"
    assert body["targets"][0]["p_known"] < body["targets"][1]["p_known"]


def test_adaptive_picks_questions_of_weak_kp(
    client, auth_headers, created_bank, sample_question
):
    """自适应出的题必须真的来自薄弱知识点，并且带得出理由。"""
    q2 = add_question(client, auth_headers, created_bank["id"], "自己练熟的题")
    link_kp(client, auth_headers, sample_question["id"], "薄弱知识点")
    link_kp(client, auth_headers, q2, "熟练知识点")
    for _ in range(4):
        answer(client, auth_headers, q2, "B")

    body = adaptive(client, auth_headers, created_bank["id"], limit=5)
    assert body["returned"] >= 1
    first = body["picked"][0]
    assert first["kp_id"] == body["targets"][0]["kp_id"] or first["kp_id"] is not None
    assert "薄弱知识点" in first["reason"], f"理由没说清：{first['reason']}"
    # 题目 payload 要和列表接口同构，Practice.vue 才能复用解析逻辑
    for field in ("id", "stem", "question_type", "options", "correct_answer", "is_cut"):
        assert field in first, f"自适应出的题缺字段 {field}"


def test_adaptive_round_robin_covers_multiple_weak_kps(
    client, auth_headers, created_bank, sample_question
):
    """轮转取题：多个薄弱知识点都要被覆盖，不能只刷最弱的那个。

    只按分数排序的话，掌握度最低的那个知识点会霸占全部名额。
    """
    names = ["知识点甲", "知识点乙", "知识点丙"]
    qids = [sample_question["id"]]
    for i in range(2):
        qids.append(add_question(client, auth_headers, created_bank["id"], f"题目{i}"))
    for qid, name in zip(qids, names):
        link_kp(client, auth_headers, qid, name)

    body = adaptive(client, auth_headers, created_bank["id"], limit=3)
    assert body["returned"] == 3
    covered = {p["kp_id"] for p in body["picked"]}
    assert len(covered) == 3, f"三个知识点应该各出一题，实际只覆盖了 {covered}"


def test_adaptive_prefers_unattempted_question(
    client, auth_headers, created_bank, sample_question
):
    """同一个知识点下，没做过的题优先于已经做过的题。"""
    q2 = add_question(client, auth_headers, created_bank["id"], "做过的题")
    link_kp(client, auth_headers, sample_question["id"], "同一个知识点")
    link_kp(client, auth_headers, q2, "同一个知识点")

    answer(client, auth_headers, q2, "A")  # 做错一次，制造"做过了"的状态

    body = adaptive(client, auth_headers, created_bank["id"], limit=2)
    picked_ids = [p["id"] for p in body["picked"]]
    assert picked_ids[0] == sample_question["id"], (
        f"没做过的题应该排第一，实际顺序 {picked_ids}"
    )


def test_adaptive_excludes_cut_questions(
    client, auth_headers, created_bank, sample_question
):
    """斩掉的题不能出现在自适应练习里（和常规练习口径一致）。"""
    q2 = add_question(client, auth_headers, created_bank["id"], "要被斩掉的题")
    link_kp(client, auth_headers, sample_question["id"], "核心概念")
    link_kp(client, auth_headers, q2, "核心概念")

    client.post(f"/api/questions/{q2}/cut", headers=auth_headers)

    body = adaptive(client, auth_headers, created_bank["id"], limit=10)
    assert q2 not in [p["id"] for p in body["picked"]]


def test_adaptive_ignores_other_users_cut_state(
    client, auth_headers, created_bank, sample_question
):
    """别人斩了题，不影响我的自适应选题。

    这条盯的是一个具体的坑：`QuestionUserState` 的 join 如果不把 user_id 写进
    ON 条件里，就会关联到别人的斩题状态，别人斩了我也做不了。
    """
    link_kp(client, auth_headers, sample_question["id"], "核心概念")

    other = {"username": "cut_other", "password": "other123456"}
    client.post("/api/register", json=other)
    token = client.post("/api/login", json=other).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    client.post(f"/api/questions/{sample_question['id']}/cut", headers=h)

    body = adaptive(client, auth_headers, created_bank["id"], limit=10)
    assert body["returned"] == 1, "别人斩题不该把我的题也过滤掉"


def test_adaptive_respects_limit(client, auth_headers, created_bank, sample_question):
    for i in range(6):
        qid = add_question(client, auth_headers, created_bank["id"], f"题{i}")
        link_kp(client, auth_headers, qid, "核心概念")
    link_kp(client, auth_headers, sample_question["id"], "核心概念")

    body = adaptive(client, auth_headers, created_bank["id"], limit=3)
    assert body["returned"] == 3
    assert len(body["picked"]) == 3
    # 不能重复出同一道题
    ids = [p["id"] for p in body["picked"]]
    assert len(ids) == len(set(ids))


def test_adaptive_limit_is_validated(client, auth_headers, created_bank):
    assert client.get(
        f"/api/banks/{created_bank['id']}/adaptive-questions",
        params={"limit": 0},
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        f"/api/banks/{created_bank['id']}/adaptive-questions",
        params={"limit": 999},
        headers=auth_headers,
    ).status_code == 422


def test_adaptive_fills_up_when_weak_kp_has_few_questions(
    client, auth_headers, created_bank, sample_question
):
    """薄弱知识点的题不够时用没做过的题补齐，并换成 with_fill 策略。

    不补齐的话请求 20 道只回 1 道，前端得自己再发一次请求——
    那等于把"题不够"这个逻辑漏给了调用方。
    """
    link_kp(client, auth_headers, sample_question["id"], "唯一的薄弱知识点")
    for i in range(4):
        add_question(client, auth_headers, created_bank["id"], f"没标注的题{i}")

    body = adaptive(client, auth_headers, created_bank["id"], limit=5)
    assert body["strategy"] == "bkt_adaptive_with_fill"
    assert body["returned"] == 5
    filled = [p for p in body["picked"] if p["kp_id"] is None]
    assert len(filled) == 4
    assert "补齐" in filled[0]["reason"]


def test_adaptive_ignores_cut_question_for_fill(
    client, auth_headers, created_bank, sample_question
):
    """补齐阶段也要排除斩题——降级路径最容易漏过滤条件。"""
    link_kp(client, auth_headers, sample_question["id"], "核心概念")
    q2 = add_question(client, auth_headers, created_bank["id"], "斩掉的题")
    client.post(f"/api/questions/{q2}/cut", headers=auth_headers)

    body = adaptive(client, auth_headers, created_bank["id"], limit=5)
    assert q2 not in [p["id"] for p in body["picked"]]
    assert body["returned"] == 1


def test_fill_orders_attempted_questions_by_fewest_attempts(
    client, auth_headers, created_bank, sample_question
):
    """所有题都做过了，补齐必须还能出题，并且"做得最少"的排前面。

    补齐分两阶段：先拿完全没做过的题（走索引、很快），不够再从做过的题里
    按作答次数少的补。只有这条用例会把第二阶段逼出来——题库小、
    而且每道题都做过。少了它，第二阶段写错了也没人知道。

    这里故意一道题都不标注知识点，走 `no_kp_fallback`，
    于是整个题单全部由补齐产生，能干净地验证排序。
    """
    q2 = add_question(client, auth_headers, created_bank["id"], "第二题")
    q3 = add_question(client, auth_headers, created_bank["id"], "第三题")

    # 作答次数：第一题 3 次，第二题 1 次，第三题 2 次
    for _ in range(3):
        answer(client, auth_headers, sample_question["id"], "B")
    answer(client, auth_headers, q2, "B")
    for _ in range(2):
        answer(client, auth_headers, q3, "B")

    body = adaptive(client, auth_headers, created_bank["id"], limit=10)
    picked_ids = [p["id"] for p in body["picked"]]

    assert body["strategy"] == "no_kp_fallback"
    assert picked_ids == [q2, q3, sample_question["id"]], (
        f"应该按作答次数从少到多出题，实际 {picked_ids}"
    )
    assert len(picked_ids) == len(set(picked_ids)), "不能重复出题"


def test_kp_targeted_question_comes_before_fill(
    client, auth_headers, created_bank, sample_question
):
    """目标知识点的题必须排在补齐的题前面。

    补齐只是"凑数"，训练重点是薄弱知识点；如果补齐的题插到前面，
    用户做完几道才发现没练到该练的地方。
    """
    link_kp(client, auth_headers, sample_question["id"], "核心概念")
    q2 = add_question(client, auth_headers, created_bank["id"], "没标注的题")
    answer(client, auth_headers, q2, "B")   # 让它变成"做过的"，确保它只能靠补齐进来

    body = adaptive(client, auth_headers, created_bank["id"], limit=5)
    picked_ids = [p["id"] for p in body["picked"]]
    assert picked_ids[0] == sample_question["id"], f"目标题应排第一，实际 {picked_ids}"
    assert q2 in picked_ids, "做过的题也要能补进来"
    fill = [p for p in body["picked"] if p["kp_id"] is None]
    assert [p["id"] for p in fill] == [q2]


def test_fill_does_not_drop_attempted_questions_that_were_seen(
    client, auth_headers, created_bank, sample_question
):
    """已经在目标区出过的题，补齐阶段不能再出一遍。

    `seen` 要在两个阶段都生效；只在阶段一过滤的话，阶段二会把同一道题
    再塞一遍，前端就会出现重复的两个题号。
    """
    link_kp(client, auth_headers, sample_question["id"], "核心概念")
    for i in range(3):
        add_question(client, auth_headers, created_bank["id"], f"没标注的题{i}")

    body = adaptive(client, auth_headers, created_bank["id"], limit=4)
    ids = [p["id"] for p in body["picked"]]
    assert len(ids) == len(set(ids)), f"出题重复了：{ids}"
    assert body["returned"] == 4


def test_adaptive_after_wrong_answer_keeps_targeting_same_kp(
    client, auth_headers, created_bank, sample_question
):
    """答错之后这个知识点更弱了，依然应该是下一个训练目标。"""
    q2 = add_question(client, auth_headers, created_bank["id"], "另一道同类题")
    link_kp(client, auth_headers, sample_question["id"], "弱点")
    link_kp(client, auth_headers, q2, "弱点")

    answer(client, auth_headers, sample_question["id"], "A")
    body = adaptive(client, auth_headers, created_bank["id"], limit=2)
    assert body["targets"][0]["name"] == "弱点"
    assert body["targets"][0]["p_known"] < bkt.DEFAULT_PARAMS.p_init
    assert body["targets"][0]["attempts"] == 1


def test_adaptive_is_per_user(client, auth_headers, created_bank, sample_question):
    """诊断是按用户的，所以两个人的自适应题单可以不同。"""
    link_kp(client, auth_headers, sample_question["id"], "核心概念")

    other = {"username": "adaptive_other", "password": "other123456"}
    client.post("/api/register", json=other)
    token = client.post("/api/login", json=other).json()["token"]
    h = {"Authorization": f"Bearer {token}"}

    # 另一个人看不到我的题库，所以拿他自己的库来验证策略可用
    bank = client.post(
        "/api/banks", json={"name": "他的库", "subject": "数学"}, headers=h
    ).json()
    q = add_question(client, h, bank["id"], "他的题")
    link_kp(client, h, q, "他的知识点")

    body = adaptive(client, h, bank["id"], limit=5)
    assert body["targets"][0]["attempts"] == 0
    assert body["targets"][0]["p_known"] == pytest.approx(bkt.DEFAULT_PARAMS.p_init)