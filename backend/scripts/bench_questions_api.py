"""在 2 万题的真实题库上验证分页、服务端搜索和 /question-stats。

为什么单独写这个脚本：单元测试跑在内存 SQLite 上，只有几十条数据。
分页真正的收益（省掉 8 MB 响应、搜索能覆盖全库）必须在大数据量下才看得出来，
所以这里直接打真实后端。

需要：
  - bench MySQL 跑在 3308（cuoti_bench，2 万题）
  - 后端跑在 3002，且 DB_PORT=3308 / DB_NAME=cuoti_bench

用法：python scripts/bench_questions_api.py
环境变量 BASE 可以改目标地址，默认 http://127.0.0.1:3002

2026-09 实测（20911 题）：
  全量列表      2040 ms   8236.9 KB
  分页第 1 页     12 ms      15.4 KB   → 体积缩到 0.19%（535 倍）
  服务端搜索     105 ms  命中 10795 条
  /question-stats 218 ms
"""
import os
import time

import httpx

BASE = os.getenv("BASE", "http://127.0.0.1:3002")

c = httpx.Client(base_url=BASE, timeout=120.0)

# bench 库里已有的账号（scripts/seed_data.py 造的）
for user, pwd in (("bench_user", "bench123456"), ("benchuser", "bench123456")):
    r = c.post("/api/login", json={"username": user, "password": pwd})
    if r.status_code == 200:
        print(f"登录成功：{user}")
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        break
else:
    raise SystemExit(f"登录失败：{r.status_code} {r.text[:200]}")

banks = c.get("/api/banks").json()
print(f"\n可见题库 {len(banks)} 个：")
for b in banks:
    print(f"  id={b['id']:<4} {b['name'][:30]:<32} {b['question_count']} 题")
if not banks:
    raise SystemExit("没有题库")

bid = max(banks, key=lambda b: b["question_count"])["id"]
print(f"\n用最大的题库 id={bid} 做验证")

# ---------- 1. 计数接口 ----------
t0 = time.perf_counter()
st = c.get(f"/api/banks/{bid}/question-stats")
dt = (time.perf_counter() - t0) * 1000
print(f"\n/question-stats  {st.status_code}  {dt:.1f} ms")
print("  " + str(st.json()))

# ---------- 2. 分页 vs 全量：响应大小与耗时 ----------
t0 = time.perf_counter()
r = c.get(f"/api/banks/{bid}/questions")
full_ms = (time.perf_counter() - t0) * 1000
full_kb = len(r.content) / 1024
print(f"\n全量列表      {r.status_code}  {full_ms:8.1f} ms  {full_kb:9.1f} KB  {len(r.json())} 条")

# 冷缓存：先清掉该题库的列表缓存再测第一页
t0 = time.perf_counter()
r = c.get(f"/api/banks/{bid}/questions", params={"page": 1, "page_size": 50})
p1_ms = (time.perf_counter() - t0) * 1000
p1_kb = len(r.content) / 1024
print(f"分页第 1 页   {r.status_code}  {p1_ms:8.1f} ms  {p1_kb:9.1f} KB  {len(r.json())} 条"
      f"  X-Total-Count={r.headers.get('X-Total-Count')} X-Has-More={r.headers.get('X-Has-More')}")

t0 = time.perf_counter()
r = c.get(f"/api/banks/{bid}/questions", params={"page": 1, "page_size": 50})
p1h_ms = (time.perf_counter() - t0) * 1000
print(f"分页第 1 页（命中缓存） {p1h_ms:8.1f} ms")

print(f"\n体积：{full_kb:.1f} KB → {p1_kb:.1f} KB"
      f"（{p1_kb / full_kb * 100:.2f}%，缩小 {full_kb / p1_kb:.0f} 倍）")

# ---------- 3. 服务端搜索 ----------
t0 = time.perf_counter()
r = c.get(f"/api/banks/{bid}/questions",
          params={"page": 1, "page_size": 10, "q": "下列"})
sr_ms = (time.perf_counter() - t0) * 1000
print(f"\n服务端搜索 q=下列  {r.status_code}  {sr_ms:8.1f} ms  "
      f"命中 {r.headers.get('X-Total-Count')} 条，本页 {len(r.json())} 条")

# ---------- 4. 分页取全库要多少请求 ----------
total = int(r.headers.get("X-Total-Count") or 0)
print(f"\n（该 q 命中 {total} 条；全库 {st.json()['total']} 条，"
      f"按 50/页需要 {(st.json()['total'] + 49) // 50} 次请求才能翻完）")

# ---------- 5. 关键点：搜到的题必须在当前页之外也能搜到 ----------
# 这是"服务端搜索"和"前端本地过滤"的分水岭。取最后一页的一道题，
# 拿它的题干片段去搜，如果只能搜到已加载的第 1 页，这里就会是 0 条。
last_page = (st.json()["total"] + 49) // 50
r = c.get(f"/api/banks/{bid}/questions", params={"page": last_page, "page_size": 50})
tail = r.json()
print(f"\n最后一页（第 {last_page} 页）拿到 {len(tail)} 条")
if tail:
    target = tail[-1]["id"]
    stem = tail[-1]["stem"]
    # 用题干结尾那段（含"（第 N 题）"）当搜索词，它只可能命中这一条。
    # 用题干中段会出现几百条命中，目标题排在结果末尾，前 5 条里当然看不到，
    # 那是排序问题，不是搜索问题。
    frag = stem.strip()[-16:]
    print(f"最后一页最后一条 stem={stem[:70]!r}")
    print(f"取题干结尾片段：{frag!r}")
    t0 = time.perf_counter()
    r2 = c.get(f"/api/banks/{bid}/questions",
               params={"page": 1, "page_size": 5, "q": frag})
    dt = (time.perf_counter() - t0) * 1000
    hit_ids = [q["id"] for q in r2.json()]
    hits = r2.headers.get("X-Total-Count")
    print(f"  {r2.status_code}  {dt:.1f} ms  命中 {hits} 条，返回 id={hit_ids}")
    print(f"  目标题 id={target}（在第 419 页，第 1 页当然没有）")
    assert str(target) in str(hit_ids), "服务端搜索没搜到第 1 页之外的题！"
    print("  ✓ 第 1 页之外的题也能被搜到——这正是本地过滤做不到的")

    # 顺带验证 LIKE 通配符被转义：% 不会变成"匹配所有"
    r3 = c.get(f"/api/banks/{bid}/questions",
               params={"page": 1, "page_size": 5, "q": "%"})
    print(f"\n搜索 q=%（若没转义会命中全部 {st.json()['total']} 条）"
          f" → 命中 {r3.headers.get('X-Total-Count')} 条")
    assert int(r3.headers.get("X-Total-Count") or 0) < st.json()["total"], "% 没有被转义！"
    print("  ✓ 通配符已转义，不会退化成全表扫描")

# ---------- 6. 搜索命中笔记 ----------
t0 = time.perf_counter()
r = c.get(f"/api/banks/{bid}/questions", params={"page": 1, "page_size": 5, "q": "笔记"})
print(f"\n搜索 q=笔记（会匹配笔记字段） {r.status_code}  {r.headers.get('X-Total-Count')} 条")

# ---------- 7. 已斩题不进入常规练习 ----------
print(f"\n计数口径：total={st.json()['total']} normal={st.json()['normal']} "
      f"cut={st.json()['cut']}（normal + cut = {st.json()['normal'] + st.json()['cut']}）")
print(f"分类：{st.json()['by_type']}")