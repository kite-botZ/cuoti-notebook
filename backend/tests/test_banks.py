"""题库与题目 CRUD 测试。

覆盖：
- 题库：创建、列表、删除、越权删除
- 题目：创建 6 种题型、列表、编辑、删除
- 参数校验：答案超范围、选项太少
"""


# ============================================================
# 题库
# ============================================================

def test_list_banks_empty(client, auth_headers):
    """新用户没有任何题库。"""
    resp = client.get("/api/banks", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_bank_success(client, auth_headers):
    """创建题库：返回 201，带 id 和初始题目数 0。"""
    resp = client.post(
        "/api/banks",
        json={"name": "英语词汇", "subject": "英语", "description": "四级核心词"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "英语词汇"
    assert data["subject"] == "英语"
    assert data["question_count"] == 0
    assert "id" in data


def test_create_bank_missing_name(client, auth_headers):
    """题库名称为空：422 校验错误。"""
    resp = client.post(
        "/api/banks",
        json={"name": "", "subject": "数学"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_list_banks_after_create(client, auth_headers, created_bank):
    """创建后能在列表里看到。"""
    resp = client.get("/api/banks", headers=auth_headers)
    assert resp.status_code == 200
    banks = resp.json()
    assert len(banks) == 1
    assert banks[0]["id"] == created_bank["id"]


def test_delete_bank(client, auth_headers, created_bank):
    """删除题库：列表里消失。"""
    resp = client.delete(
        f"/api/banks/{created_bank['id']}",
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # 再查列表，应为空
    resp = client.get("/api/banks", headers=auth_headers)
    assert resp.json() == []


def test_delete_bank_not_owner(client, auth_headers, created_bank):
    """用户 B 不能删用户 A 的题库。"""
    # 注册第二个用户
    client.post("/api/register", json={
        "username": "user_b", "password": "pass123456"
    })
    login = client.post("/api/login", json={
        "username": "user_b", "password": "pass123456"
    })
    user_b_headers = {"Authorization": f"Bearer {login.json()['token']}"}

    # 用户 B 尝试删用户 A 的题库
    resp = client.delete(
        f"/api/banks/{created_bank['id']}",
        headers=user_b_headers,
    )
    assert resp.status_code == 404  # 题库存不存在或无权访问


# ============================================================
# 题目 CRUD
# ============================================================

def test_create_single_choice(client, auth_headers, created_bank):
    """创建单选题：返回 201。"""
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
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["question_type"] == "single"
    assert data["options"] == ["1", "2", "3", "4"]
    # 安全设计：返回里不带正确答案
    assert "correct_answer" not in data


def test_create_multiple_choice(client, auth_headers, created_bank):
    """创建多选题：正确答案是多字母组合。"""
    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "以下哪些是编程语言？",
            "question_type": "multiple",
            "options": ["Python", "HTML", "Java", "CSS"],
            "correct_answer": "AC",
            "explanation": "",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text


def test_create_judge(client, auth_headers, created_bank):
    """创建判断题：后端自动补两个固定选项。"""
    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "地球是平的。",
            "question_type": "judge",
            "correct_answer": "B",
            "explanation": "",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["options"] == ["正确", "错误"]


def test_create_blank(client, auth_headers, created_bank):
    """创建填空题：无选项，答案是文本。"""
    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "中国的首都是____。",
            "question_type": "blank",
            "correct_answer": "北京",
            "explanation": "",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["options"] == []


def test_create_short(client, auth_headers, created_bank):
    """创建简答题：无选项，参考答案是文本。"""
    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "简述 TCP 三次握手。",
            "question_type": "short",
            "correct_answer": "客户端发送SYN，服务端回复SYN+ACK，客户端再发送ACK",
            "explanation": "",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text


def test_create_calc(client, auth_headers, created_bank):
    """创建计算题。"""
    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "计算 12 × 8 的值。",
            "question_type": "calc",
            "correct_answer": "96",
            "explanation": "",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text


def test_create_question_invalid_answer(client, auth_headers, created_bank):
    """正确答案超出选项范围：422。"""
    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "测试题",
            "question_type": "single",
            "options": ["1", "2"],
            "correct_answer": "E",  # 超出 2 个选项
            "explanation": "",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_create_question_too_few_options(client, auth_headers, created_bank):
    """单选题选项少于 2 个：422。"""
    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "测试题",
            "question_type": "single",
            "options": ["只有一个"],
            "correct_answer": "A",
            "explanation": "",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_list_questions(client, auth_headers, created_bank):
    """创建题目后能在列表里看到。"""
    client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "测试题 1",
            "question_type": "single",
            "options": ["A1", "B1"],
            "correct_answer": "A",
            "explanation": "",
        },
        headers=auth_headers,
    )

    resp = client.get(
        f"/api/banks/{created_bank['id']}/questions",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    questions = resp.json()
    assert len(questions) == 1
    assert questions[0]["stem"] == "测试题 1"
    # 题目列表里也不返回答案
    assert "correct_answer" not in questions[0]


def test_update_question(client, auth_headers, created_bank):
    """编辑题目：只改传了的字段。"""
    # 先创建
    created = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "原题干",
            "question_type": "single",
            "options": ["A1", "B1"],
            "correct_answer": "A",
            "explanation": "原解析",
        },
        headers=auth_headers,
    ).json()
    qid = created["id"]

    # 只改题干
    resp = client.put(
        f"/api/questions/{qid}",
        json={"stem": "新题干"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["stem"] == "新题干"
    # 其他字段没变
    assert data["options"] == ["A1", "B1"]
    assert data["question_type"] == "single"


def test_delete_question(client, auth_headers, created_bank):
    """删除题目。"""
    created = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={
            "stem": "待删除",
            "question_type": "single",
            "options": ["A1", "B1"],
            "correct_answer": "A",
            "explanation": "",
        },
        headers=auth_headers,
    ).json()
    qid = created["id"]

    resp = client.delete(f"/api/questions/{qid}", headers=auth_headers)
    assert resp.status_code == 200

    # 列表中应消失
    resp = client.get(
        f"/api/banks/{created_bank['id']}/questions",
        headers=auth_headers,
    )
    assert len(resp.json()) == 0