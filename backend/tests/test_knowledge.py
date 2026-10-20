"""知识点体系与「大模型自动打标」的测试。

分三层：

1. **纯函数**：名称归一化、宽泛词过滤、模型输出解析 —— 这层最容易出边界问题，
   必须覆盖模型的各种「不听话」输出（markdown 围栏、前后废话、id 对不上、权重离谱）。
2. **落库逻辑**：`get_or_create_kp` 去重、`apply_tags` 的覆盖语义。
3. **接口**：知识点 CRUD、题目关联、auto-tag（用假客户端，不真的跑模型）、覆盖率统计。

模型调用通过依赖注入的 `client` 替换成假客户端，
所以这组用例在没装 Ollama 的机器上也能跑。
"""

import json
import re

import pytest

from app.knowledge import (
    apply_tags,
    build_tag_prompt,
    get_or_create_kp,
    is_useful_kp,
    normalize_kp_name,
    parse_tag_response,
    tag_questions,
)
from app.models import KnowledgePoint, QuestionKnowledgePoint


# ============================================================
# 1. 纯函数
# ============================================================

@pytest.mark.parametrize("raw,expected", [
    ("  二次函数顶点式  ", "二次函数顶点式"),
    ("二次函数（顶点式）", "二次函数"),
    ("二次函数(顶点式)", "二次函数"),
    ("二叉树遍历、", "二叉树遍历"),
    ("TCP    三次握手", "TCP 三次握手"),
    ("", ""),
    (None, ""),
])
def test_normalize_kp_name(raw, expected):
    assert normalize_kp_name(raw) == expected


def test_normalize_kp_name_truncates():
    assert len(normalize_kp_name("知" * 200)) == 60


@pytest.mark.parametrize("name", ["数学", "考点", "知识点", "基础", "", "a"])
def test_is_useful_kp_rejects_broad_or_short(name):
    assert is_useful_kp(name) is False


@pytest.mark.parametrize("name", ["二次函数顶点式", "索引下推", "TCP 三次握手"])
def test_is_useful_kp_accepts_specific(name):
    assert is_useful_kp(name) is True


def test_build_tag_prompt_contains_every_question():
    class Q:
        def __init__(self, i, stem, options, qtype="single"):
            self.id, self.stem, self.options, self.question_type = i, stem, options, qtype

    qs = [Q(1, "第一题", ["甲", "乙"]), Q(2, "第二题", [])]
    prompt = build_tag_prompt(qs, "数学")
    assert "[id=1]" in prompt and "[id=2]" in prompt
    assert "数学" in prompt
    assert "选项：甲 / 乙" in prompt
    assert "只输出 JSON" in prompt


# ---------- 模型输出解析：各种不听话的情况 ----------

def test_parse_plain_json():
    raw = json.dumps({"items": [
        {"id": 1, "knowledge_points": [{"name": "二次函数顶点式", "weight": 1.0}]},
    ]})
    assert parse_tag_response(raw, {1}) == {1: [{"name": "二次函数顶点式", "weight": 1.0}]}


def test_parse_markdown_fence():
    raw = '```json\n{"items":[{"id":1,"knowledge_points":[{"name":"索引下推"}]}]}\n```'
    assert parse_tag_response(raw, {1}) == {1: [{"name": "索引下推", "weight": 1.0}]}


def test_parse_with_leading_chatter():
    raw = '好的，下面是标注结果：\n{"items":[{"id":2,"knowledge_points":[{"name":"死锁预防"}]}]}'
    assert 2 in parse_tag_response(raw, {2})


def test_parse_bare_array():
    raw = '[{"id":3,"knowledge_points":[{"name":"B+树"}]}]'
    assert 3 in parse_tag_response(raw, {3})


def test_parse_drops_unknown_ids():
    """模型编了个不存在的 id，必须丢掉。"""
    raw = '{"items":[{"id":999,"knowledge_points":[{"name":"不存在的题"}]}]}'
    assert parse_tag_response(raw, {1, 2}) == {}


def test_parse_drops_broad_names():
    raw = '{"items":[{"id":1,"knowledge_points":[{"name":"数学"},{"name":"考点"}]}]}'
    assert parse_tag_response(raw, {1}) == {}


def test_parse_clamps_weight():
    raw = '{"items":[{"id":1,"knowledge_points":[{"name":"红黑树","weight":9}]}]}'
    assert parse_tag_response(raw, {1})[1][0]["weight"] == 1.0
    raw = '{"items":[{"id":1,"knowledge_points":[{"name":"红黑树","weight":0}]}]}'
    assert parse_tag_response(raw, {1})[1][0]["weight"] == 0.1


def test_parse_caps_kp_count():
    kps = [{"name": f"知识点{i}"} for i in range(8)]
    raw = json.dumps({"items": [{"id": 1, "knowledge_points": kps}]})
    assert len(parse_tag_response(raw, {1})[1]) == 3


def test_parse_dedupes_same_name():
    raw = ('{"items":[{"id":1,"knowledge_points":'
           '[{"name":"红黑树"},{"name":"红黑树（补充）"}]}]}')
    # 括号内容被归一化掉，变同名 -> 去重
    assert len(parse_tag_response(raw, {1})[1]) == 1


def test_parse_garbage_returns_empty():
    assert parse_tag_response("模型今天不想干活", {1}) == {}
    assert parse_tag_response("", {1}) == {}
    assert parse_tag_response("{坏掉的 json", {1}) == {}


def test_parse_accepts_plain_string_kps():
    raw = '{"items":[{"id":1,"knowledge_points":["索引下推"]}]}'
    assert parse_tag_response(raw, {1})[1][0]["name"] == "索引下推"


# ============================================================
# 2. 落库
# ============================================================

def test_get_or_create_kp_dedupes(db):
    a = get_or_create_kp(db, "二次函数顶点式", "数学")
    b = get_or_create_kp(db, "二次函数顶点式", "数学")
    db.commit()
    assert a.id == b.id
    assert db.query(KnowledgePoint).count() == 1


def test_get_or_create_kp_same_name_different_subject(db):
    get_or_create_kp(db, "函数", "数学")
    get_or_create_kp(db, "函数", "物理")
    db.commit()
    assert db.query(KnowledgePoint).count() == 2


def test_apply_tags_replaces_when_asked(db, sample_question):
    qid = sample_question["id"]
    assert apply_tags(db, qid, [{"name": "整数加法", "weight": 1.0}], "数学") == 1
    db.commit()
    # 重新标注同一道题：旧关联应被覆盖，不会累积
    assert apply_tags(db, qid, [{"name": "自然数", "weight": 1.0}], "数学",
                      replace=True) == 1
    db.commit()

    names = [
        kp.name for kp in db.query(KnowledgePoint)
        .join(QuestionKnowledgePoint, QuestionKnowledgePoint.kp_id == KnowledgePoint.id)
        .filter(QuestionKnowledgePoint.question_id == qid).all()
    ]
    assert names == ["自然数"]


def test_apply_tags_skips_broad_names(db, sample_question):
    qid = sample_question["id"]
    count = apply_tags(db, qid, [{"name": "数学"}, {"name": "整数加法"}], "数学")
    db.commit()
    assert count == 1


# ============================================================
# 3. 假模型客户端 + auto-tag
# ============================================================

def make_fake_client(prefix="知识点"):
    """按 prompt 里的 [id=N] 生成对应数量的知识点。"""
    class FakeClient:
        calls = 0

        def __init__(self, host=None, **kwargs):
            pass

        def chat(self, model=None, messages=None, format=None, options=None):
            FakeClient.calls += 1
            prompt = messages[0]["content"]
            ids = [int(x) for x in re.findall(r"\[id=(\d+)\]", prompt)]
            items = [
                {"id": i, "knowledge_points": [{"name": f"{prefix}{i}", "weight": 1.0}]}
                for i in ids
            ]
            return {"message": {"content": json.dumps({"items": items}, ensure_ascii=False)}}

    return FakeClient


def test_tag_questions_batches_and_reports(db, client, auth_headers, created_bank):
    from app.models import Question

    bank_id = created_bank["id"]
    for i in range(5):
        client.post(
            f"/api/banks/{bank_id}/questions",
            json={"stem": f"题目{i}", "question_type": "single",
                  "options": ["甲", "乙"], "correct_answer": "A", "explanation": ""},
            headers=auth_headers,
        )
    questions = db.query(Question).filter(Question.bank_id == bank_id).all()

    fake = make_fake_client()
    report = tag_questions(
        db=db, questions=questions, subject="数学",
        client=fake(), model="fake", batch_size=2,
    )
    db.commit()

    assert report["requested"] == 5
    assert report["tagged"] == 5
    assert report["batches"] == 3          # 2 + 2 + 1
    assert report["failed_batches"] == 0
    assert report["links"] == 5
    assert db.query(QuestionKnowledgePoint).count() == 5


def test_tag_questions_survives_one_bad_batch(db, created_bank):
    """某一批模型报错，其它批必须继续，不能整批失败。"""
    from app.models import Question

    class FlakyClient:
        def __init__(self):
            self.n = 0

        def chat(self, **kwargs):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("模型超时")
            prompt = kwargs["messages"][0]["content"]
            ids = [int(x) for x in re.findall(r"\[id=(\d+)\]", prompt)]
            return {"message": {"content": json.dumps(
                {"items": [{"id": i, "knowledge_points": [{"name": f"KP{i}"}]}
                           for i in ids]})}}

    for i in range(4):
        db.add(Question(bank_id=created_bank["id"], stem=f"题{i}",
                        question_type="single", options=["a", "b"],
                        correct_answer="A", explanation=""))
    db.commit()
    questions = db.query(Question).filter(Question.bank_id == created_bank["id"]).all()

    report = tag_questions(db=db, questions=questions, subject="综合",
                           client=FlakyClient(), model="fake", batch_size=2)
    db.commit()

    assert report["failed_batches"] == 1
    assert report["tagged"] == 2           # 第二批成功
    assert "模型超时" in report["errors"][0]


# ============================================================
# 4. HTTP 接口
# ============================================================

def test_create_and_list_kp(client):
    resp = client.post("/api/knowledge-points",
                       json={"name": "二次函数顶点式", "subject": "数学"})
    assert resp.status_code == 201
    kp_id = resp.json()["id"]

    listed = client.get("/api/knowledge-points?subject=数学").json()
    assert [k["id"] for k in listed] == [kp_id]


def test_create_kp_rejects_duplicate(client):
    body = {"name": "索引下推", "subject": "数据库原理"}
    assert client.post("/api/knowledge-points", json=body).status_code == 201
    assert client.post("/api/knowledge-points", json=body).status_code == 400


def test_create_kp_rejects_broad_name(client):
    resp = client.post("/api/knowledge-points", json={"name": "数学", "subject": "数学"})
    assert resp.status_code == 422


def test_kp_tree(client):
    parent = client.post("/api/knowledge-points",
                         json={"name": "二次函数", "subject": "数学"}).json()
    client.post("/api/knowledge-points",
                json={"name": "顶点式", "subject": "数学", "parent_id": parent["id"]})

    tree = client.get("/api/knowledge-points?subject=数学&tree=true").json()
    assert len(tree) == 1
    assert tree[0]["name"] == "二次函数"
    assert tree[0]["children"][0]["name"] == "顶点式"


def test_set_question_kps_manual(client, auth_headers, sample_question):
    qid = sample_question["id"]
    resp = client.put(
        f"/api/questions/{qid}/knowledge-points",
        json={"knowledge_points": [{"name": "整数加法", "weight": 1.0}]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["knowledge_points"][0]["name"] == "整数加法"
    assert body["knowledge_points"][0]["source"] == "manual"

    got = client.get(f"/api/questions/{qid}/knowledge-points", headers=auth_headers)
    assert len(got.json()) == 1


def test_question_kps_requires_ownership(client, auth_headers, sample_question):
    other = {"username": "kp_intruder", "password": "intruder123"}
    client.post("/api/register", json=other)
    token = client.post("/api/login", json=other).json()["token"]

    resp = client.get(
        f"/api/questions/{sample_question['id']}/knowledge-points",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_auto_tag_dry_run_does_not_call_model(client, auth_headers, created_bank):
    bank_id = created_bank["id"]
    client.post(
        f"/api/banks/{bank_id}/questions",
        json={"stem": "干跑测试", "question_type": "single",
              "options": ["甲", "乙"], "correct_answer": "A", "explanation": ""},
        headers=auth_headers,
    )
    resp = client.post(
        f"/api/banks/{bank_id}/questions/auto-tag?dry_run=true", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["requested"] == 1
    assert "[id=" in body["prompt_preview"]


def test_auto_tag_with_fake_model(client, auth_headers, created_bank, monkeypatch, db):
    """把 ollama.Client 换成假客户端，验证接口层的真实写库流程。"""
    import ollama
    monkeypatch.setattr(ollama, "Client", make_fake_client("考点"))

    bank_id = created_bank["id"]
    for i in range(3):
        client.post(
            f"/api/banks/{bank_id}/questions",
            json={"stem": f"自动标注题{i}", "question_type": "single",
                  "options": ["甲", "乙"], "correct_answer": "A", "explanation": ""},
            headers=auth_headers,
        )

    resp = client.post(f"/api/banks/{bank_id}/questions/auto-tag?limit=10",
                       headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tagged"] == 3
    assert body["links"] == 3
    assert db.query(QuestionKnowledgePoint).count() == 3


def test_auto_tag_skips_already_tagged(client, auth_headers, created_bank, monkeypatch):
    """默认只处理没标注过的题，第二次调用应该没活儿干。"""
    import ollama
    monkeypatch.setattr(ollama, "Client", make_fake_client("考点"))

    bank_id = created_bank["id"]
    client.post(
        f"/api/banks/{bank_id}/questions",
        json={"stem": "只标一次", "question_type": "single",
              "options": ["甲", "乙"], "correct_answer": "A", "explanation": ""},
        headers=auth_headers,
    )
    first = client.post(f"/api/banks/{bank_id}/questions/auto-tag", headers=auth_headers)
    assert first.json()["tagged"] == 1

    second = client.post(f"/api/banks/{bank_id}/questions/auto-tag", headers=auth_headers)
    assert second.json()["requested"] == 0
    assert "都已经标过" in second.json()["message"]


def test_knowledge_coverage(client, auth_headers, created_bank, monkeypatch):
    import ollama
    monkeypatch.setattr(ollama, "Client", make_fake_client("考点"))

    bank_id = created_bank["id"]
    for i in range(2):
        client.post(
            f"/api/banks/{bank_id}/questions",
            json={"stem": f"覆盖率题{i}", "question_type": "single",
                  "options": ["甲", "乙"], "correct_answer": "A", "explanation": ""},
            headers=auth_headers,
        )
    client.post(f"/api/banks/{bank_id}/questions/auto-tag?limit=1", headers=auth_headers)

    cov = client.get(f"/api/banks/{bank_id}/knowledge-coverage", headers=auth_headers).json()
    assert cov["questions_total"] == 2
    assert cov["questions_tagged"] == 1
    assert cov["questions_untagged"] == 1
    assert cov["coverage"] == 0.5


def test_auto_tag_requires_ownership(client, auth_headers, created_bank):
    other = {"username": "tag_intruder", "password": "intruder123"}
    client.post("/api/register", json=other)
    token = client.post("/api/login", json=other).json()["token"]

    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions/auto-tag",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
