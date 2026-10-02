"""答题判分、题目状态、进度统计测试。

覆盖：
- 6 种题型的判分（单选 / 多选 / 判断 / 填空 / 简答 / 计算）
- 答错时 wrong_count 递增
- 收藏 / 斩题 切换
- 批量斩题
- 题库进度统计
"""


# ============================================================
# 答题判分
# ============================================================

def test_answer_single_correct(client, auth_headers, sample_question):
    """单选答对：correct=True。"""
    resp = client.post(
        f"/api/questions/{sample_question['id']}/answer",
        json={"selected_answer": "B"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["correct"] is True
    assert data["correct_answer"] == "B"
    assert data["explanation"] == "1 + 1 = 2"


def test_answer_single_wrong(client, auth_headers, sample_question):
    """单选答错：correct=False。"""
    resp = client.post(
        f"/api/questions/{sample_question['id']}/answer",
        json={"selected_answer": "A"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["correct"] is False


def test_answer_multiple_order_irrelevant(client, auth_headers, created_bank):
    """多选：答案顺序无关，"CA" 和 "AC" 都算对。"""
    q = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "以下哪些是编程语言？",
            "question_type": "multiple",
            "options": ["Python", "HTML", "Java", "CSS"],
            "correct_answer": "AC",
            "explanation": "",
        },
        headers=auth_headers,
    ).json()

    # 顺序反着写
    resp = client.post(
        f"/api/questions/{q['id']}/answer",
        json={"selected_answer": "CA"},
        headers=auth_headers,
    )
    assert resp.json()["correct"] is True


def test_answer_multiple_wrong(client, auth_headers, created_bank):
    """多选：少选一个算错。"""
    q = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "以下哪些是编程语言？",
            "question_type": "multiple",
            "options": ["Python", "HTML", "Java", "CSS"],
            "correct_answer": "AC",
            "explanation": "",
        },
        headers=auth_headers,
    ).json()

    resp = client.post(
        f"/api/questions/{q['id']}/answer",
        json={"selected_answer": "A"},
        headers=auth_headers,
    )
    assert resp.json()["correct"] is False


def test_answer_blank_exact(client, auth_headers, created_bank):
    """填空：答案精确匹配。"""
    q = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "中国的首都是____。",
            "question_type": "blank",
            "correct_answer": "北京",
            "explanation": "",
        },
        headers=auth_headers,
    ).json()

    resp = client.post(
        f"/api/questions/{q['id']}/answer",
        json={"selected_answer": "北京"},
        headers=auth_headers,
    )
    assert resp.json()["correct"] is True


def test_answer_short_fuzzy_match(client, auth_headers, created_bank):
    """简答：去空格和标点后匹配，应判对。"""
    q = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "简述 TCP 三次握手。",
            "question_type": "short",
            "correct_answer": "客户端发送SYN，服务端回复SYN+ACK，客户端再发送ACK",
            "explanation": "",
        },
        headers=auth_headers,
    ).json()

    # 加空格和标点，应该还是判对
    resp = client.post(
        f"/api/questions/{q['id']}/answer",
        json={"selected_answer": "客户端发送 SYN，服务端回复 SYN+ACK，客户端再发送 ACK。"},
        headers=auth_headers,
    )
    assert resp.json()["correct"] is True


def test_answer_short_wrong(client, auth_headers, created_bank):
    """简答：完全不对的答案判错。"""
    q = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "简述 TCP 三次握手。",
            "question_type": "short",
            "correct_answer": "客户端发送SYN，服务端回复SYN+ACK，客户端再发送ACK",
            "explanation": "",
        },
        headers=auth_headers,
    ).json()

    resp = client.post(
        f"/api/questions/{q['id']}/answer",
        json={"selected_answer": "我不知道"},
        headers=auth_headers,
    )
    assert resp.json()["correct"] is False


def test_answer_wrong_increments_wrong_count(
    client, auth_headers, created_bank, sample_question
):
    """答错一次：错题列表里出现这道题，wrong_count = 1。"""
    client.post(
        f"/api/questions/{sample_question['id']}/answer",
        json={"selected_answer": "A"},  # 错
        headers=auth_headers,
    )

    resp = client.get(
        f"/api/banks/{created_bank['id']}/questions?filter_type=wrong",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    wrong_list = resp.json()
    assert len(wrong_list) == 1
    assert wrong_list[0]["id"] == sample_question["id"]
    assert wrong_list[0]["wrong_count"] == 1


def test_answer_correct_does_not_add_to_wrong(
    client, auth_headers, created_bank, sample_question
):
    """答对：不会进错题本。"""
    client.post(
        f"/api/questions/{sample_question['id']}/answer",
        json={"selected_answer": "B"},  # 对
        headers=auth_headers,
    )

    resp = client.get(
        f"/api/banks/{created_bank['id']}/questions?filter_type=wrong",
        headers=auth_headers,
    )
    assert resp.json() == []


# ============================================================
# 收藏 / 斩题
# ============================================================

def test_toggle_favorite(client, auth_headers, sample_question):
    """收藏：再点一次取消。"""
    url = f"/api/questions/{sample_question['id']}/favorite"

    r1 = client.post(url, headers=auth_headers)
    assert r1.json()["is_favorite"] is True

    r2 = client.post(url, headers=auth_headers)
    assert r2.json()["is_favorite"] is False


def test_toggle_cut(client, auth_headers, sample_question):
    """斩题：再点一次恢复。"""
    url = f"/api/questions/{sample_question['id']}/cut"

    r1 = client.post(url, headers=auth_headers)
    assert r1.json()["is_cut"] is True

    r2 = client.post(url, headers=auth_headers)
    assert r2.json()["is_cut"] is False


def test_cut_filter_returns_answer(
    client, auth_headers, created_bank, sample_question
):
    """斩题列表会返回正确答案（因为已移出练习，允许查看）。"""
    client.post(
        f"/api/questions/{sample_question['id']}/cut",
        headers=auth_headers,
    )

    resp = client.get(
        f"/api/banks/{created_bank['id']}/questions?filter_type=cut",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    # 关键：斩题列表里有答案
    assert "correct_answer" in items[0]
    assert items[0]["correct_answer"] == "B"


def test_batch_cut(client, auth_headers, created_bank):
    """批量斩题：一次斩 3 道题。"""
    # 先建 3 道题
    ids = []
    for i in range(3):
        q = client.post(
            f"/api/banks/{created_bank['id']}/questions",
            json={
                "stem": f"测试题 {i}",
                "question_type": "single",
                "options": ["A1", "B1"],
                "correct_answer": "A",
                "explanation": "",
            },
            headers=auth_headers,
        ).json()
        ids.append(q["id"])

    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions/batch-cut",
        json={"question_ids": ids, "is_cut": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 3

    # 验证都在斩题列表里
    cut_list = client.get(
        f"/api/banks/{created_bank['id']}/questions?filter_type=cut",
        headers=auth_headers,
    ).json()
    assert len(cut_list) == 3


# ============================================================
# 笔记
# ============================================================

def test_save_note(client, auth_headers, sample_question):
    """保存笔记：覆盖式更新。"""
    url = f"/api/questions/{sample_question['id']}/note"

    r1 = client.put(url, json={"note": "第一版笔记"}, headers=auth_headers)
    assert r1.status_code == 200
    assert r1.json()["note"] == "第一版笔记"

    r2 = client.put(url, json={"note": "第二版笔记"}, headers=auth_headers)
    assert r2.json()["note"] == "第二版笔记"


def test_note_filter(client, auth_headers, created_bank, sample_question):
    """有笔记的题出现在笔记列表里。"""
    client.put(
        f"/api/questions/{sample_question['id']}/note",
        json={"note": "重点复习"},
        headers=auth_headers,
    )

    resp = client.get(
        f"/api/banks/{created_bank['id']}/questions?filter_type=note",
        headers=auth_headers,
    )
    assert len(resp.json()) == 1


# ============================================================
# 进度统计
# ============================================================

def test_bank_progress_empty(client, auth_headers, created_bank):
    """没答过题：正确率 0。"""
    resp = client.get(
        f"/api/banks/{created_bank['id']}/progress",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["question_count"] == 0
    assert data["attempt_count"] == 0
    assert data["accuracy"] == 0


def test_bank_progress_after_answers(
    client, auth_headers, created_bank, sample_question
):
    """答 2 次，1 对 1 错：正确率 50%。"""
    # 答对
    client.post(
        f"/api/questions/{sample_question['id']}/answer",
        json={"selected_answer": "B"},
        headers=auth_headers,
    )
    # 答错
    client.post(
        f"/api/questions/{sample_question['id']}/answer",
        json={"selected_answer": "A"},
        headers=auth_headers,
    )

    resp = client.get(
        f"/api/banks/{created_bank['id']}/progress",
        headers=auth_headers,
    )
    data = resp.json()
    assert data["question_count"] == 1
    assert data["attempt_count"] == 2
    assert data["correct_count"] == 1
    assert data["accuracy"] == 0.5


# ============================================================
# 越权保护
# ============================================================

def test_cannot_answer_other_users_question(
    client, auth_headers, created_bank, sample_question
):
    """用户 B 不能答用户 A 的题。"""
    # 注册用户 B
    client.post("/api/register", json={
        "username": "user_b", "password": "pass123456"
    })
    login = client.post("/api/login", json={
        "username": "user_b", "password": "pass123456"
    })
    user_b_headers = {"Authorization": f"Bearer {login.json()['token']}"}

    resp = client.post(
        f"/api/questions/{sample_question['id']}/answer",
        json={"selected_answer": "B"},
        headers=user_b_headers,
    )
    assert resp.status_code == 404