"""知识库 / RAG / 知识点接口的端到端冒烟测试。

**这个脚本需要后端已经在跑**（pytest 覆盖不到跨接口的真实链路）：
注册 → 登录 → 建题库 → 上传讲义 → 列表 → 切分片段 → 统计 → 检索 →
模型信息 → 题目知识点增删回读 → 覆盖率 → 打标 dry_run → 失败路径 → 删除级联。

用法：

    python scripts/smoke_knowledge_api.py
    python scripts/smoke_knowledge_api.py --base-url http://127.0.0.1:3000

为什么要单独写一个：前端页面（frontend/src/views/Knowledge.vue）调的接口
分布在 rag.py / knowledge.py 两个模块里，字段名一旦对不上，页面会静默显示空。
pytest 是进程内 TestClient，测不出"页面拿到的东西形状对不对"，所以这里用
真实 HTTP 打一遍，逐字段检查。

⚠️ 会往 base-url 指向的**当前数据库**写测试数据（用户名带随机后缀）。
默认跑完会清理自己上传的文档；`--keep` 可以留下来手工看页面。
不要在线上环境跑。
"""

from __future__ import annotations

import argparse
import json
import random
import sys

import httpx

OK = "[OK]"
BAD = "[!!]"

results: list[tuple[bool, str]] = []


def check(cond: bool, label: str, extra: str = "") -> bool:
    ok = bool(cond)
    results.append((ok, label))
    print(f"{OK if ok else BAD} {label}" + (f"  -> {extra}" if extra else ""))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库接口端到端冒烟")
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--keep", action="store_true", help="跑完保留上传的文档，方便打开页面看")
    args = parser.parse_args()

    tag = random.randint(10000, 99999)
    client = httpx.Client(base_url=args.base_url, timeout=180.0)

    # ---------- 0. 注册 + 登录 ----------
    r = client.post("/api/register", json={"username": f"kbsmoke{tag}", "password": "smoke123456"})
    if r.status_code not in (201, 400):
        print(f"{BAD} 注册失败: {r.status_code} {r.text[:200]}")
        return 1
    r = client.post("/api/login", json={"username": f"kbsmoke{tag}", "password": "smoke123456"})
    if not check(r.status_code == 200, "登录", str(r.status_code)):
        print(r.text[:300])
        return 1
    client.headers["Authorization"] = f"Bearer {r.json()['token']}"

    # ---------- 1. 建题库 ----------
    r = client.post(
        "/api/banks",
        json={"name": f"冒烟题库{tag}", "subject": "判断推理", "description": "smoke"},
    )
    check(r.status_code == 201, "建题库", str(r.status_code))
    bank_id = r.json()["id"]

    # ---------- 2. 上传讲义（Markdown：解析 → 切分 → 向量化）----------
    md = (
        "# 图形推理 · 对称性\n\n"
        "对称轴的方向判断：先看整体轮廓是否规则，再找是否存在一条直线把图形分成镜像的两半。\n\n"
        "## 轴对称\n\n"
        "若一条直线沿其折叠后两部分完全重合，则称该图形关于这条直线轴对称。\n\n"
        "## 中心对称\n\n"
        "若图形绕某点旋转 180 度后与自身重合，则称其为中心对称图形。\n\n"
        "## 常见陷阱\n\n"
        "对称轴数量与方向都要数清楚，题干只问方向时不要多写数量。\n"
    )
    r = client.post(
        "/api/knowledge-docs",
        files={"file": ("对称性笔记.md", md.encode("utf-8"), "text/markdown")},
        data={"title": "图形推理·对称性笔记", "subject": "判断推理"},
    )
    check(r.status_code in (200, 201), "上传讲义", str(r.status_code))
    body = r.json() if r.status_code in (200, 201) else {}
    check(body.get("status") == "ready", "讲义入库成功（status=ready）", str(body.get("message"))[:120])
    check((body.get("chunk_count") or 0) > 0, "切出了片段", f"chunk_count={body.get('chunk_count')}")
    doc_id = body.get("id")
    created_docs = [doc_id] if doc_id else []

    # ---------- 3. 文档列表 / 片段 / 统计 ----------
    r = client.get("/api/knowledge-docs")
    docs = r.json()
    check(r.status_code == 200 and any(d["id"] == doc_id for d in docs), "文档列表含刚上传的文档", f"{len(docs)} 份")

    r = client.get(f"/api/knowledge-docs/{doc_id}/chunks", params={"limit": 5})
    chunks = r.json()
    check(r.status_code == 200 and len(chunks["chunks"]) > 0, "查看切分片段", f"{len(chunks['chunks'])} 段")
    for field in ("index", "chapter", "page", "char_count", "has_embedding", "text"):
        check(field in chunks["chunks"][0], f"片段的 {field} 字段存在")

    r = client.get("/api/rag/stats")
    st = r.json()
    shown = {k: st[k] for k in ("documents", "documents_ready", "chunks", "embedding_coverage")}
    check(r.status_code == 200 and st["documents"] >= 1, "知识库统计", json.dumps(shown, ensure_ascii=False))

    # ---------- 4. 检索 ----------
    r = client.post("/api/rag/search", json={"query": "对称轴的方向怎么判断", "top_k": 5, "alpha": 0.5})
    res = r.json()
    check(r.status_code == 200, "检索接口", str(r.status_code))
    check(res.get("mode") in ("bm25", "hybrid", "vector"), "检索模式有值", str(res.get("mode")))
    check(
        len(res.get("hits", [])) > 0,
        "召回了片段",
        f"candidates={res.get('candidates')} hits={len(res.get('hits', []))}",
    )
    if res.get("hits"):
        hit = res["hits"][0]
        for field in (
            "chunk_id", "doc_id", "title", "text", "chapter", "page",
            "score", "bm25_score", "vector_score", "coverage",
        ):
            check(field in hit, f"检索结果的 {field} 字段存在")
        print(f"    命中标题 = {hit['title']!r}  页 = {hit['page']}  score = {hit['score']}")

    r = client.post("/api/rag/search", json={"query": "中心对称", "top_k": 3, "alpha": 0.0})
    check(r.json().get("mode") == "bm25", "alpha=0 时为纯 BM25 模式", str(r.json().get("mode")))

    # ---------- 5. 模型信息 ----------
    r = client.get("/api/ai/info")
    info = r.json()
    check(r.status_code == 200 and "provider" in info, "模型信息接口",
          f"provider={info.get('provider')} chat={info.get('chat_model')} embed={info.get('embed_model')}")
    print(f"    client_ready={info.get('client_ready')}  error={info.get('error')!r}")

    # ---------- 6. 题目 + 知识点 ----------
    r = client.post(f"/api/banks/{bank_id}/questions", json={
        "stem": "下列图形中，对称轴方向与其他三项不同的是？",
        "question_type": "single",
        "options": ["等边三角形", "正方形", "等腰梯形", "圆"],
        "correct_answer": "C",
        "explanation": "考查对称轴方向。",
    })
    check(r.status_code == 201, "新增题目", str(r.status_code))
    qid = r.json()["id"]

    r = client.put(f"/api/questions/{qid}/knowledge-points", json={
        "knowledge_points": [{"name": "对称轴方向", "weight": 1.0}, {"name": "轴对称图形", "weight": 0.8}],
    })
    check(r.status_code == 200, "手工设置知识点", str(r.status_code))
    check(len(r.json()["knowledge_points"]) == 2, "知识点写回两条",
          json.dumps([k["name"] for k in r.json()["knowledge_points"]], ensure_ascii=False))

    r = client.get(f"/api/questions/{qid}/knowledge-points")
    check(r.status_code == 200 and len(r.json()) == 2, "回读知识点",
          json.dumps([k["name"] for k in r.json()], ensure_ascii=False))

    r = client.get("/api/knowledge-points", params={"tree": "true"})
    tree = r.json()
    check(r.status_code == 200 and isinstance(tree, list), "知识点树接口", f"{len(tree)} 个根节点")
    if tree:
        check("children" in tree[0], "树节点带 children 字段")

    r = client.get(f"/api/banks/{bank_id}/knowledge-coverage")
    cov = r.json()
    check(r.status_code == 200 and cov["questions_tagged"] == 1, "知识点覆盖率",
          json.dumps({k: cov[k] for k in ("questions_total", "questions_tagged", "coverage")}, ensure_ascii=False))

    # ---------- 7. 打标 dry_run（不调模型，页面「预览提示词」用它）----------
    # auto-tag 默认只挑还没打标的题，所以先加一道没标签的，否则接口会正确地
    # 返回「都已经标过了」，dry_run 分支走不到。
    r = client.post(f"/api/banks/{bank_id}/questions", json={
        "stem": "中心对称图形旋转多少度后与自身重合？",
        "question_type": "judge",
        "options": [],
        "correct_answer": "A",
        "explanation": "考查中心对称的定义。",
    })
    check(r.status_code == 201, "新增一道未打标的题", str(r.status_code))

    r = client.post(f"/api/banks/{bank_id}/questions/auto-tag", params={"limit": 5, "dry_run": "true"})
    check(r.status_code == 200 and r.json().get("dry_run") is True, "打标预览（dry_run）",
          str(r.json().get("message"))[:80])
    check(bool(r.json().get("prompt_preview")), "预览返回了提示词文本")

    # ---------- 8. 失败路径 ----------
    r = client.post("/api/knowledge-docs",
                    files={"file": ("x.exe", b"MZ\x90\x00", "application/octet-stream")},
                    data={"title": "坏文件", "subject": "综合"})
    check(r.status_code == 422, "不支持的文件格式被拒", f"{r.status_code}")

    r = client.post("/api/knowledge-docs",
                    files={"file": ("empty.md", b"", "text/markdown")},
                    data={"title": "空文件", "subject": "综合"})
    check(r.status_code == 422, "空文件被拒", str(r.status_code))

    r = client.post("/api/knowledge-docs",
                    files={"file": ("blank.txt", b"   \n\n  ", "text/plain")},
                    data={"title": "只有空白", "subject": "综合"})
    check(r.status_code in (200, 201), "空白文本返回 200 而不是 500", str(r.status_code))
    check(r.json().get("status") == "failed", "空白文本被判定入库失败", str(r.json().get("message"))[:90])
    if r.json().get("id"):
        created_docs.append(r.json()["id"])

    # ---------- 9. 删除级联 ----------
    r = client.delete(f"/api/knowledge-docs/{doc_id}")
    check(r.status_code == 200, "删除文档", str(r.status_code))
    r = client.get(f"/api/knowledge-docs/{doc_id}/chunks")
    check(r.status_code == 404, "删除后片段接口返回 404", str(r.status_code))

    # ---------- 10. 清理 ----------
    if args.keep:
        print(f"\n--keep 已指定，保留文档 id = {created_docs}")
    else:
        for did in created_docs:
            client.delete(f"/api/knowledge-docs/{did}")
        left = [d for d in client.get("/api/knowledge-docs").json() if d["id"] in created_docs]
        check(not left, "冒烟数据已清理干净", f"剩余 {len(left)} 份")

    # ---------- 汇总 ----------
    failed = [label for ok, label in results if not ok]
    print("\n" + "=" * 60)
    print(f"共 {len(results)} 项检查，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项")
    for label in failed:
        print(f"  {BAD} {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())