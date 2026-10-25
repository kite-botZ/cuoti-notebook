"""回归测试：多轮对抗式审查（黑盒端到端 + 逐行代码审查）挖出来的真缺陷。

这个文件不是"再补一点覆盖率"，而是**每一条都对应一个真实复现过的故障**。
共同特征是：它们全都能在 SQLite 测试环境里"看起来正常"，或者被
现有用例的弱断言放过，所以必须专门钉住。按严重程度分组。

一个反复出现的教训写在最前面：**SQLite 不校验字段长度、不执行严格类型**，
所以"写入超长值 → MySQL 1406 → 500 + 整事务回滚"这类缺陷在测试里永远是绿的。
下面的长度类用例因此断言的是"接口层主动挡住（422）"，而不是"数据库报错"。
"""
import pytest

from app.rag.chunker import chunk_pages, is_heading
from app.rag.loader import Page
from app.rag.retriever import mode_of


# ============================================================
# 1. 判分正确性
# ============================================================

@pytest.mark.parametrize("answer,expected", [
    ("未找到", True),
    ("未找到。", True),      # ← 曾经被判错：差一个句号
    ("未找到！", True),
    ("  未找到  ", True),
    ("未找到！！！", True),
    ("找到了", False),
])
def test_blank_uses_loose_matching(client, auth_headers, created_bank, answer, expected):
    """填空题必须和简答/计算一样做宽松匹配。

    历史缺陷：宽松匹配的分支写的是 `("short", "calc")`，漏了 `blank`，
    填空落到精确比较。于是「未找到。」被判错 → 进错题本（wrong_count+1）
    → 掌握度下降，**答对却污染三处数据**。README 明确写了填空也宽松匹配，
    所以这是实现和文档的直接矛盾，而且正好打在项目主打的"避免误判"卖点上。
    """
    qid = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={"stem": "TCP 三次握手找不到端口时返回什么？", "question_type": "blank",
              "options": [], "correct_answer": "未找到", "explanation": "略"},
        headers=auth_headers,
    ).json()["id"]

    resp = client.post(f"/api/questions/{qid}/answer",
                       json={"selected_answer": answer}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["correct"] is expected


def test_short_answer_loose_matching_still_works(client, auth_headers, created_bank):
    """简答的宽松匹配不能被上面的改动破坏（去掉空格与标点）。"""
    qid = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={"stem": "描述三次握手", "question_type": "short", "options": [],
              "correct_answer": "客户端发送SYN，服务端回复SYN+ACK，客户端再发送ACK",
              "explanation": "略"},
        headers=auth_headers,
    ).json()["id"]
    resp = client.post(
        f"/api/questions/{qid}/answer",
        json={"selected_answer": "客户端发送 SYN，服务端回复 SYN+ACK，客户端再发送 ACK。"},
        headers=auth_headers,
    )
    assert resp.json()["correct"] is True


# ============================================================
# 2. 长度限制：必须在接口层变成 422，而不是 500
# ============================================================

def test_overlong_selected_answer_is_422_not_500(client, auth_headers, created_bank):
    """501 字的答案必须被挡住。

    历史缺陷：`answer_attempts.selected_answer` 是 varchar(500)，而
    `AnswerCreate.selected_answer` 没有任何长度约束 → 501 字撞 MySQL 1406
    → 500，**并且整个事务回滚**：判分结果、答题历史、错题计数、掌握度更新
    全部丢失。长解答正是简答题的常态，这条出现在最自然的演示路径上。
    """
    qid = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={"stem": "写一段很长的推导", "question_type": "short", "options": [],
              "correct_answer": "略", "explanation": ""},
        headers=auth_headers,
    ).json()["id"]

    ok = client.post(f"/api/questions/{qid}/answer",
                     json={"selected_answer": "啊" * 500}, headers=auth_headers)
    assert ok.status_code == 200, "500 字正好是列宽，应该放行"

    too_long = client.post(f"/api/questions/{qid}/answer",
                           json={"selected_answer": "啊" * 501}, headers=auth_headers)
    assert too_long.status_code == 422, "超长答案要给 422 的明确提示，不能是 500"


def test_overlong_correct_answer_is_422_not_500(client, auth_headers, created_bank):
    """简答/计算的参考答案放宽到 255 字，超出给 422。

    历史缺陷：列宽只有 varchar(50)，50 字以上的参考答案（一句话或一个算式）
    直接 500，用户完全不知道该改什么。
    """
    payload = {
        "stem": "解释一下快速排序的平均复杂度推导", "question_type": "short",
        "options": [], "explanation": "",
    }
    # 60 字：旧列宽下必崩，新列宽下必须成功
    resp = client.post(f"/api/banks/{created_bank['id']}/questions",
                       json={**payload, "correct_answer": "啊" * 60},
                       headers=auth_headers)
    assert resp.status_code == 201, "60 字的参考答案属于常态，必须能存进去"

    too_long = client.post(f"/api/banks/{created_bank['id']}/questions",
                           json={**payload, "correct_answer": "啊" * 256},
                           headers=auth_headers)
    assert too_long.status_code == 422


def test_overlong_username_is_422_not_500(client):
    """60 字的用户名必须被挡住。

    历史缺陷：`RegisterBody.username` 无长度约束，`users.username` 是
    varchar(50) → 注册页输入长用户名就是裸 500。
    """
    resp = client.post("/api/register",
                       json={"username": "x" * 60, "password": "Abcd1234"})
    assert resp.status_code == 422

    assert client.post("/api/register",
                       json={"username": "x" * 50, "password": "Abcd1234"}
                       ).status_code == 201


# ============================================================
# 3. 只含空白的输入
# ============================================================

def test_whitespace_only_stem_is_rejected(client, auth_headers, created_bank):
    """纯空格题干不是题干。

    历史缺陷：`QuestionCreate.stem` 只有 `min_length=1`，`"   "` 长度是 3
    能过校验，随后 `.strip()` 变成 `""` 入库——列表里出现一道题干为空的题。
    """
    resp = client.post(f"/api/banks/{created_bank['id']}/questions",
                       json={"stem": "   ", "question_type": "single",
                             "options": ["甲", "乙"], "correct_answer": "A"},
                       headers=auth_headers)
    assert resp.status_code == 422


# ============================================================
# 4. 认知诊断：没判分的作答不能算成答错
# ============================================================

def _kp_and_question(client, auth_headers, bank_id, stem):
    """建一个知识点 + 一道挂在该知识点上的单选题。"""
    kp = client.post("/api/knowledge-points",
                     json={"name": f"回归知识点{stem}", "subject": "数学"},
                     headers=auth_headers).json()
    qid = client.post(
        f"/api/banks/{bank_id}/questions",
        json={"stem": stem, "question_type": "short", "options": [],
              "correct_answer": "略", "explanation": ""},
        headers=auth_headers,
    ).json()["id"]
    resp = client.put(f"/api/questions/{qid}/knowledge-points",
                      json={"knowledge_points": [{"name": kp["name"], "weight": 1.0}]},
                      headers=auth_headers)
    assert resp.status_code == 200
    return kp, qid


def test_image_answer_without_self_assessment_is_not_evidence(
    client, auth_headers, created_bank
):
    """上传图片草稿、用户还没自评 → 这次作答不构成"会不会"的证据。

    历史缺陷：`need_self_check=True` 时 `is_correct` 仍然是 `False`，然后被
    原样喂给 `record_attempt`。一次上传图片就把知识点掌握度从 0.30 打到
    0.1959（"上传草稿"被诊断成"不会"），同时那行 `is_correct=0` 还进了
    正确率统计——错题本说没错、统计说错了、诊断说退步了，三处口径互相矛盾。
    """
    kp, qid = _kp_and_question(client, auth_headers, created_bank["id"], "图片题回归")
    before = client.get("/api/banks/%d/mastery" % created_bank["id"],
                        headers=auth_headers).json()
    # 先确认基线是个真数字：否则下面 after == before 可能只是 None == None，
    # 用例会在"什么都没测到"的情况下变绿。
    assert before["overall_p_known"] is not None, before

    resp = client.post(f"/api/questions/{qid}/answer",
                       json={"selected_answer": "![draft](http://x/y.png)"},
                       headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["need_self_check"] is True
    assert body["assessed"] is False
    assert body["mastery_changes"] == []

    after = client.get("/api/banks/%d/mastery" % created_bank["id"],
                       headers=auth_headers).json()
    # 掌握度一个数都不该动
    assert after["overall_p_known"] == before["overall_p_known"]

    # 错题本也不该有它
    wrong = client.get(f"/api/banks/{created_bank['id']}/questions?filter_type=wrong",
                       headers=auth_headers).json()
    assert qid not in [q["id"] for q in wrong]


def test_image_answer_with_self_assessment_updates_mastery(
    client, auth_headers, created_bank
):
    """用户自评"答对了"时，这次作答就是有效证据，要更新掌握度。"""
    kp, qid = _kp_and_question(client, auth_headers, created_bank["id"], "自评题回归")
    before = client.get("/api/banks/%d/mastery" % created_bank["id"],
                        headers=auth_headers).json()
    assert before["overall_p_known"] is not None, before

    body = client.post(
        f"/api/questions/{qid}/answer",
        json={"selected_answer": "![draft](http://x/y.png)", "self_correct": True},
        headers=auth_headers,
    ).json()
    assert body["assessed"] is True
    assert body["correct"] is True
    assert body["mastery_changes"], "自评结果应该推动掌握度"

    after = client.get("/api/banks/%d/mastery" % created_bank["id"],
                       headers=auth_headers).json()
    assert after["overall_p_known"] > before["overall_p_known"]


def test_mastery_unchanged_when_no_knowledge_point(client, auth_headers, created_bank):
    """没打标的题不改变任何掌握度（也不能因为没标签就拒绝判题）。"""
    qid = client.post(
        f"/api/banks/{created_bank['id']}/questions",
        json={"stem": "没打标的题", "question_type": "single",
              "options": ["甲", "乙"], "correct_answer": "A", "explanation": ""},
        headers=auth_headers,
    ).json()["id"]
    resp = client.post(f"/api/questions/{qid}/answer",
                       json={"selected_answer": "B"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["correct"] is False
    assert resp.json()["mastery_changes"] == []


# ============================================================
# 5. 章节/页码元数据（"引用出处"的数据源）
# ============================================================

def test_chapter_detected_when_paragraphs_are_blank_line_separated():
    """空行分段时也要认得出标题。

    历史缺陷：`is_heading` 判断的是整个 block，而空行分段（讲义/Word/Markdown
    最常见的排法）下一个 block 是「标题行 + 整段正文」的多行文本，
    `is_heading` 必然 False → 章节路径一直为空 → 全文 chapter 落到
    兜底的「正文」。于是每次"引用出处"都是错的，而这个字段是直接显示给
    用户的、README 也明确承诺保留章节。
    """
    text = (
        "一、中心理解题\n"
        "总原则是先看问题，再用句号划分层次，理清脉络层次与主体一致。\n"
        "\n"
        "二、细节判断题\n"
        "细节题要回到原文逐句比对，注意偷换概念和无中生有。\n"
    )
    chunks = chunk_pages([Page(page_no=1, text=text)], target=60, overlap=0)
    chapters = [c.chapter for c in chunks]
    assert any("中心理解题" in c for c in chapters), chapters
    assert all(c != "" for c in chapters), chapters


def test_chapter_changes_after_second_heading_with_overlap():
    """第二个标题之后的片段必须换章节，不能冻结在第一章。

    历史缺陷：`buf_chapter` 只在 `buf` 为空时赋值，而默认 overlap=80 时
    `flush()` 会把上一段的尾巴留在 buf 里 → 首次 flush 之后 buf 永不为空
    → 章节冻结在第一个标题上。实测"正文是项目经历、出处却标成教育经历"。
    """
    text = "\n".join([
        "一、中心理解题",
        "总原则：先看问题，再用句号划分层次，理清脉络层次与主体一致。" * 4,
        "二、细节判断题",
        "细节题要回到原文逐句比对，注意偷换概念和无中生有。" * 4,
    ])
    chunks = chunk_pages([Page(page_no=1, text=text)], target=150, overlap=80)
    later = [c for c in chunks if "细节题要回到原文" in c.text]
    assert later, "应该至少有一个片段落在第二章"
    assert all("细节判断题" in c.chapter for c in later), [c.chapter for c in later]


def test_last_chunk_keeps_page_number():
    """最后一个片段不能丢页码。

    历史缺陷：收尾那一处 flush 直接用 `buf_page`，而重叠会把 `buf_page`
    重置成 None（只有 flush() 里有 last_page 兜底），于是单页文档的
    末段 page=None。
    """
    chunks = chunk_pages(
        [Page(page_no=7, text="这是页七的内容，够长以便切分。" * 40)],
        target=100, overlap=50,
    )
    assert chunks
    assert all(c.page == 7 for c in chunks), [c.page for c in chunks]


# ============================================================
# 6. 检索模式标签
# ============================================================

def test_mode_of_labels_pure_bm25_at_alpha_zero():
    """α=0 是纯关键词检索，标签必须是 bm25。

    历史缺陷：只判断 `alpha >= 1.0`，其余一律 "hybrid"，于是 α=0 显示成
    混合检索。这个字段的用处正是让人看出"混合到底有没有比单路好"，
    标错了它就没有意义；前端还会照着它显示"本次是混合检索"。
    """
    assert mode_of(0.0, used_vector=True) == "bm25"
    assert mode_of(0.3, used_vector=True) == "hybrid"
    assert mode_of(1.0, used_vector=True) == "vector"
    assert mode_of(0.5, used_vector=False) == "bm25"


# ============================================================
# 7. 批量导入的逐行容错
# ============================================================

def test_json_import_survives_non_object_element(client, auth_headers, created_bank):
    """数组里混进非对象元素时，只丢那一条，其余照常入库。

    历史缺陷：`_normalize(item)` 第一件事是 `item.get("stem")`，而调用处
    只捕获 `ImportError`，所以传字符串/数字会抛 AttributeError → **整包 500**，
    连一条错误清单都没有。"逐行容错 + 结构化错误清单"是这个功能的主卖点，
    一个脏元素不该让另外 99 条好题也进不来。
    """
    import json as _json
    payload = _json.dumps([
        {"stem": "好题一", "question_type": "single",
         "options": ["甲", "乙"], "correct_answer": "A"},
        "我是一个字符串不是对象",
        12345,
        {"stem": "好题二", "question_type": "single",
         "options": ["甲", "乙"], "correct_answer": "B"},
    ], ensure_ascii=False).encode("utf-8")

    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions/import",
        files={"file": ("q.json", payload, "application/json")},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["inserted"] == 2, body
    locations = [i["location"] for i in body["issues"]]
    # 两条脏元素各记一条，位置是原始下标
    assert "第 2 条" in locations
    assert "第 3 条" in locations


def test_invalid_kp_name_does_not_wipe_existing_tags(client, auth_headers, created_bank):
    """非法知识点名必须 422，而且**不能清空**题目原有的标注。

    历史缺陷：`apply_tags(replace=True)` 先覆盖后校验，所以传 `"数学"`
    （过于宽泛）或空名字会返回 200 + `knowledge_points: []`，用户原有的
    标注被静默清空，之后这道题的作答也不再更新任何掌握度。
    同一个名字在 `POST /api/knowledge-points` 上是 422，两条路径口径不一致。
    """
    kp, qid = _kp_and_question(client, auth_headers, created_bank["id"], "清空标注回归")
    # 注意：GET 返回的是**列表**（PUT 才包成 {"knowledge_points": [...]}）
    assert client.get(f"/api/questions/{qid}/knowledge-points",
                      headers=auth_headers).json(), "前置条件：已有标注"

    resp = client.put(f"/api/questions/{qid}/knowledge-points",
                      json={"knowledge_points": [{"name": "数学", "weight": 1.0}]},
                      headers=auth_headers)
    assert resp.status_code == 422, resp.text

    # 关键断言：原有标注必须还在
    still = client.get(f"/api/questions/{qid}/knowledge-points",
                       headers=auth_headers).json()
    assert still, "非法名字不该清掉已有标注"

    # 空名字同样 422，且同样不动数据
    assert client.put(f"/api/questions/{qid}/knowledge-points",
                      json={"knowledge_points": [{"name": "  ", "weight": 1.0}]},
                      headers=auth_headers).status_code == 422
    assert client.get(f"/api/questions/{qid}/knowledge-points",
                      headers=auth_headers).json()


def test_valid_kp_put_replaces_tags(client, auth_headers, created_bank):
    """合法名字仍然正常覆盖（上面加的校验不能把正常路径堵死）。"""
    kp, qid = _kp_and_question(client, auth_headers, created_bank["id"], "覆盖标注回归")
    new_name = f"新知识点{kp['id']}"
    resp = client.put(f"/api/questions/{qid}/knowledge-points",
                      json={"knowledge_points": [{"name": new_name, "weight": 1.0}]},
                      headers=auth_headers)
    assert resp.status_code == 200, resp.text
    names = [k["name"] for k in resp.json()["knowledge_points"]]
    assert names == [new_name], names


def test_auto_tag_remaining_counts_questions_not_links(client, auth_headers, created_bank, db):
    """`remaining` 必须数**题数**，不是"题目↔知识点"关联条数。

    历史缺陷：直接对 `QuestionKnowledgePoint` 整行 `.distinct().count()`，
    数的是 qkp.id（一行 = 一条关联）。而打标提示词允许一题挂 1-3 个知识点，
    所以一题挂 3 个就被算成 3 道题——`remaining` 偏小甚至为负。实测同一个
    题库里 auto-tag 说 remaining=0、而 knowledge-coverage 说 untagged=2。

    这里直接验修好的那个计数函数（auto-tag 的 remaining 就是它算出来的），
    不走模型：`remaining` 只在真正调用 LLM 的那条分支里返回，
    测试环境不该依赖本地大模型。
    """
    from app.models import QuestionKnowledgePoint
    from app.routes.knowledge import _tagged_question_count

    for stem in ("打标题一", "打标题二"):
        client.post(f"/api/banks/{created_bank['id']}/questions",
                    json={"stem": stem, "question_type": "single",
                          "options": ["甲", "乙"], "correct_answer": "A"},
                    headers=auth_headers)

    # 给第一题挂 3 个知识点（提示词就是要求"每题 1~3 个"）
    names = [f"三挂知识点{i}" for i in range(3)]
    for n in names:
        client.post("/api/knowledge-points", json={"name": n, "subject": "数学"},
                    headers=auth_headers)
    q1 = client.get(f"/api/banks/{created_bank['id']}/questions",
                    headers=auth_headers).json()[0]["id"]
    resp = client.put(f"/api/questions/{q1}/knowledge-points",
                      json={"knowledge_points": [{"name": n, "weight": 1.0} for n in names]},
                      headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()["knowledge_points"]) == 3, "前置条件：一题挂 3 个知识点"

    # 这就是当初算错的那两种数法，差距一目了然
    link_rows = db.query(QuestionKnowledgePoint).count()
    assert link_rows == 3, "关联有 3 条"
    assert _tagged_question_count(db, created_bank["id"]) == 1, "但只是 1 道题"

    # 必须和权威口径（coverage）一致
    coverage = client.get(f"/api/banks/{created_bank['id']}/knowledge-coverage",
                          headers=auth_headers).json()
    assert coverage["questions_tagged"] == 1
    assert coverage["questions_untagged"] == 1
    # 修好的口径：总数 - 已打标题数 = 1（旧算法会得到 2-3 = -1）
    total = 2
    assert max(0, total - _tagged_question_count(db, created_bank["id"])) == \
        coverage["questions_untagged"]


# ============================================================
# 8. 讲义（RAG）—— 详见 test_rag.py 的鉴权小节
# ============================================================

def test_upload_failed_document_returns_4xx(client, auth_headers):
    """入库失败不能回 201 Created。

    历史缺陷：装饰器写死 `status_code=201`，失败分支直接 return payload，
    于是"入库失败"也是 201——监控、脚本、axios 全都只看状态码，只能看出"成功"。
    """
    resp = client.post(
        "/api/knowledge-docs",
        files={"file": ("blank.txt", b"   \n\n  ", "text/plain")},
        data={"title": "只有空白", "subject": "行测"},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text
    # 原因仍要原样带回来（前端靠它显示"扫描件需要 OCR"这类具体提示）
    assert resp.json()["message"]
    assert resp.json()["status"] == "failed"


def test_json_import_warns_on_unsupported_question_type(client, auth_headers, created_bank):
    """非法题型要给出警告，不能静默改成单选。

    历史缺陷：`_normalize` 把非法题型直接降级成 "single" 且不产生任何 issue，
    于是"题型=essay"的题被当成单选入库、答案 A 的含义完全变了，用户零提示；
    而手工加题走的是 422「不支持的题型」。两条路径对同一份数据必须口径一致。
    """
    import json as _json
    payload = _json.dumps([{
        "stem": "题型非法", "question_type": "essay",
        "options": ["甲", "乙"], "correct_answer": "A",
    }], ensure_ascii=False).encode("utf-8")

    resp = client.post(
        f"/api/banks/{created_bank['id']}/questions/import",
        files={"file": ("q.json", payload, "application/json")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["inserted"] == 1, "仍然入库，但必须报出来"
    warnings = [i for i in body["issues"] if i.get("severity") == "warning"]
    assert any("题型" in w["reason"] for w in warnings), body["issues"]