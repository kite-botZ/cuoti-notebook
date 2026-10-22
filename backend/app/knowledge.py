"""知识点标注：让大模型给题目打知识点标签。

## 为什么用大模型做这件事

手工给几百道题打知识点不现实；规则匹配（关键词表）又脆弱。
大模型在「这道题考什么」这件事上表现相当好，而且能给出**可复用**的知识点名称
（比如把「求 y=x²-4x+3 的顶点坐标」归到「二次函数顶点式」）。

这一步是整条链路的地基：**认知诊断的诊断对象是知识点，不是题目**。
没有知识点，后面的掌握度估计、自适应选题都无从谈起。

## 输出为什么要这么严

模型可能返回 markdown 代码块、多余的说明文字、甚至 id 对不上。
所以这里做四层兜底：
1. 去掉 ```json 围栏；
2. 只取第一个 `{...}` 或 `[...]` 片段；
3. 校验 id 必须在本次请求的题目里；
4. 名称归一化 + 权重裁剪 + 同题去重。
任何一条解析不出来就跳过，绝不让模型输出把入库流程搞崩。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models import KnowledgePoint, Question, QuestionKnowledgePoint

# 一次让模型处理几道题。
# 太大：prompt 变长、耗时长、超时风险高；太小：调用次数多、总耗时反而更长。
DEFAULT_BATCH_SIZE = int(os.getenv("TAG_BATCH_SIZE", "10"))

MAX_KP_PER_QUESTION = 3
KP_NAME_MAX_LEN = 60

_CN_PUNCT = "，。、；：！？（）【】《》“”‘’·—…"

# 模型经常把学科大词当知识点输出，这类名称没有诊断价值，直接丢弃
_TOO_BROAD = {
    "数学", "语文", "英语", "物理", "化学", "生物", "历史", "地理", "政治",
    "综合", "通用", "基础", "知识", "考点", "知识点", "其他",
}


def normalize_kp_name(name: Any) -> str:
    """把模型给的知识点名称整理成入库用的形式。

    - 去空白、去掉末尾的标点
    - 去掉括号里的补充说明（「二次函数（顶点式）」→「二次函数」）——
      括号内容经常是模型临时加的限定语，留着会产生大量近似重复的知识点
    - 截断超长名称
    """
    s = str(name or "").strip()
    if not s:
        return ""
    s = re.sub(r"[（(][^）)]*[）)]", "", s)          # 去掉括号补充
    s = s.strip().strip(_CN_PUNCT).strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) > KP_NAME_MAX_LEN:
        s = s[:KP_NAME_MAX_LEN]
    return s


def is_useful_kp(name: str) -> bool:
    """过滤掉「数学」「考点」这类没有诊断价值的大词。"""
    if not name or len(name) < 2:
        return False
    return name not in _TOO_BROAD


def build_tag_prompt(questions: Iterable[Question], subject: str) -> str:
    """拼打标用的 prompt。

    ## 输出示例里的 id 必须用真实题号

    这里踩过一个真实的坑：示例原来是写死的 `{"id":1,...}`。题号从 1 开始的批次
    看不出问题，但主库里第一批待标注的题号是 2、3、4——4B 的小模型直接把示例里的
    `id=1` 照抄了回来，于是每一条都因为"题号不在这一批里"被丢掉，
    整批白跑，而错误信息只说"没有解析出有效知识点"，完全看不出是题号的问题。

    所以示例里的 id 取这一批**第一道题的真实 id**，并额外加一条"照抄题号"的规则。
    句号后面的兜底在 `parse_tag_response`（未知题号一律丢弃），那是必须保留的
    安全属性，不能为了容错而放宽。
    """
    questions = list(questions)
    sample_id = questions[0].id if questions else 1

    lines = [
        "你是学科教研专家，负责给题库里的题目标注考查的知识点。",
        "",
        "要求：",
        f"1. 每道题给 1~{MAX_KP_PER_QUESTION} 个知识点，不要超过 {MAX_KP_PER_QUESTION} 个；",
        "2. 知识点名称必须具体、可复用，例如「二次函数顶点式」；",
        "   禁止输出「数学」「函数」「考点」这类过于宽泛的词；",
        "3. 知识点名称不要带括号注释、不要带标点；",
        "4. 主考查点 weight 给 1.0，次要考查点给 0.5；",
        "5. 每道题的 id 必须原样照抄题目行里的 [id=N]，不要自己编号；",
        "6. 只输出 JSON，不要输出任何解释文字。",
        "",
        "输出格式：",
        f'{{"items":[{{"id":{sample_id},"knowledge_points":'
        f'[{{"name":"二次函数顶点式","weight":1.0}}]}}]}}',
        f"（其中 id 要换成每道题自己的题号，例如本题库里就有 "
        f"{', '.join(str(q.id) for q in questions[:3])} 等题号）",
        "",
        f"学科：{subject}",
        "题目：",
    ]
    for q in questions:
        block = [f"[id={q.id}] {q.stem}"]
        if q.options:
            block.append("选项：" + " / ".join(str(o) for o in q.options))
        if q.question_type:
            block.append(f"题型：{q.question_type}")
        lines.append("\n".join(block))
    return "\n".join(lines)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)
_JSON_START_RE = re.compile(r"[\[{]")


def _extract_json(raw: str) -> Any:
    """从模型输出里抠出 JSON。容忍 markdown 围栏和前后废话。"""
    if not raw:
        return None
    text = raw.strip()

    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass

    # 退一步：从第一个 { 或 [ 开始，尝试逐步截断到能解析为止
    start = _JSON_START_RE.search(text)
    if not start:
        return None
    candidate = text[start.start():]
    for end in range(len(candidate), 0, -1):
        chunk = candidate[:end]
        if chunk[-1] not in "}]":
            continue
        try:
            return json.loads(chunk)
        except (ValueError, TypeError):
            continue
    return None


def _returned_ids(raw: str) -> list[int]:
    """只把模型返回里的题号抠出来，用于错误信息。

    不判断合法性——恰恰是想看到"模型编了哪些题号"，所以照单全收。
    """
    data = _extract_json(raw)
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    ids: list[int] = []
    for item in items:
        if isinstance(item, dict):
            try:
                ids.append(int(item.get("id")))
            except (TypeError, ValueError):
                continue
    return ids


def parse_tag_response(raw: str, valid_ids: set[int]) -> dict[int, list[dict]]:
    """解析模型返回，得到 {question_id: [{"name":..., "weight":...}]}。

    任何不合法的东西都丢掉，绝不抛异常——标注失败只是少打几个标签，
    不能把整个请求搞成 500。
    """
    data = _extract_json(raw)
    if data is None:
        return {}

    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return {}

    result: dict[int, list[dict]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            qid = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if qid not in valid_ids:
            continue

        raw_kps = item.get("knowledge_points") or item.get("kps") or item.get("knowledge")
        if not isinstance(raw_kps, list):
            continue

        seen: set[str] = set()
        kps: list[dict] = []
        for kp in raw_kps:
            if isinstance(kp, str):
                name, weight = kp, 1.0
            elif isinstance(kp, dict):
                name = kp.get("name") or kp.get("知识点") or ""
                try:
                    weight = float(kp.get("weight", 1.0))
                except (TypeError, ValueError):
                    weight = 1.0
            else:
                continue

            name = normalize_kp_name(name)
            if not is_useful_kp(name) or name in seen:
                continue

            # 权重裁剪到 [0.1, 1.0]：模型偶尔会给出 0 或 5
            weight = max(0.1, min(1.0, weight))
            seen.add(name)
            kps.append({"name": name, "weight": round(weight, 2)})

            if len(kps) >= MAX_KP_PER_QUESTION:
                break

        if kps:
            result[qid] = kps

    return result


# ------------------------------------------------------------
# 落库
# ------------------------------------------------------------

def get_or_create_kp(db: Session, name: str, subject: str) -> KnowledgePoint:
    """按 (subject, name) 取知识点，没有就建。"""
    kp = (
        db.query(KnowledgePoint)
        .filter(KnowledgePoint.subject == subject, KnowledgePoint.name == name)
        .first()
    )
    if kp:
        return kp
    kp = KnowledgePoint(name=name, subject=subject)
    db.add(kp)
    db.flush()          # 拿到自增 id，但先不提交
    return kp


def apply_tags(
    db: Session,
    question_id: int,
    tags: list[dict],
    subject: str,
    source: str = "llm",
    replace: bool = True,
) -> int:
    """把一道题的知识点关联写进去，返回写入条数。

    `replace=True` 时先删掉这道题原有的关联（重新标注场景）；
    否则只补充缺失的关联。
    """
    if replace:
        db.query(QuestionKnowledgePoint).filter(
            QuestionKnowledgePoint.question_id == question_id
        ).delete(synchronize_session=False)

    count = 0
    for tag in tags:
        name = normalize_kp_name(tag.get("name"))
        if not is_useful_kp(name):
            continue
        kp = get_or_create_kp(db, name, subject)
        db.add(QuestionKnowledgePoint(
            question_id=question_id,
            kp_id=kp.id,
            weight=float(tag.get("weight", 1.0)),
            source=source,
        ))
        count += 1
    return count


# ------------------------------------------------------------
# 批量标注
# ------------------------------------------------------------

def tag_questions(
    db: Session,
    questions: list[Question],
    subject: str,
    client: Any,
    model: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    source: str = "llm",
) -> dict:
    """调用大模型批量标注，返回统计信息。

    `client` 走依赖注入（只要有个 `.chat(model=..., messages=..., format="json")`
    就行），这样单测里可以塞一个假客户端，不用真的跑模型。

    **每批都会 `db.commit()`**，所以这个函数不是原子的：调用方不用再提交一次，
    但也要知道中途失败会留下已标注的部分（见循环末尾的说明）。
    """
    report = {
        "requested": len(questions),
        "tagged": 0,
        "links": 0,
        "batches": 0,
        "failed_batches": 0,
        "errors": [],
    }
    if not questions:
        return report

    batch_size = max(1, batch_size)
    for i in range(0, len(questions), batch_size):
        batch = questions[i:i + batch_size]
        prompt = build_tag_prompt(batch, subject)
        report["batches"] += 1
        try:
            resp = client.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                format="json",          # 让 Ollama 强制输出 JSON
                options={"temperature": 0.1},
            )
            raw = (resp or {}).get("message", {}).get("content", "")
        except Exception as e:          # noqa: BLE001 - 单批失败不影响其它批
            report["failed_batches"] += 1
            report["errors"].append(f"第 {report['batches']} 批调用失败：{e}")
            continue

        parsed = parse_tag_response(raw, {q.id for q in batch})
        if not parsed:
            report["failed_batches"] += 1
            # 把模型实际返回的题号写进错误信息。原来只说"没有解析出有效知识点"，
            # 而真正的失败原因（模型把示例里的 id=1 照抄回来，题号压根不在这一批里）
            # 完全看不出来，排查要重新手工跑一遍模型。
            returned_ids = _returned_ids(raw)
            report["errors"].append(
                f"第 {report['batches']} 批没有解析出有效知识点"
                f"（本批题号 {sorted(q.id for q in batch)}，"
                f"模型返回的题号 {returned_ids}）"
            )
            continue

        for qid, tags in parsed.items():
            report["links"] += apply_tags(db, qid, tags, subject, source=source)
            report["tagged"] += 1

        # 每批提交一次，而不是等整个请求跑完再提交。
        #
        # 为什么必须这样：本地 4B 模型一批 10 道题要 22 秒，标 300 道就是 11 分钟，
        # 标满 2 万题要十几个小时。只在最后 commit 的话，中间任何一次超时、
        # 断连或者进程被杀，前面几十分钟的推理结果全部丢掉——而模型调用是
        # 这整条链路里最贵的一步，重跑一次要再花同样的时间。
        #
        # 代价是"一次请求不再是原子操作"：中途失败会留下已经标好的部分。
        # 这对打标是**可以接受甚至是想要的**——未标注的题会被下一轮
        # overwrite=false 的调用接着标，天然支持断点续标。
        db.commit()

    return report
