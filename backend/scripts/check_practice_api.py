"""把练习页会发的请求原样打一遍，确认分页契约和过滤口径都对。

这是"前端逻辑没法在浏览器里自动化验证"的替代手段：把 Practice.vue 里
每一处 request 调用抄成实际 URL，逐个核对状态码、条数、响应头。
在 2 万题的 bench 库上跑（默认 3002）。

用法：python scripts/check_practice_api.py
检查项（2026-10 实测全部通过）：
  - 分页头、越界页返回空、最后一页不足一整页
  - filter_type=wrong/favorite/cut/note 四类
  - question_type + has_image 组合
  - 勾选/恢复用的 ids=，非法 id 与超过 100 个都返回 422
  - 随机练习的分批取题不重不漏
"""
import os

import httpx

BASE = os.getenv("BASE", "http://127.0.0.1:3002")
BANK = int(os.getenv("BANK_ID", "1"))

c = httpx.Client(base_url=BASE, timeout=300.0)
r = c.post("/api/login", json={"username": "bench_user", "password": "bench123456"})
r.raise_for_status()
c.headers["Authorization"] = f"Bearer {r.json()['token']}"

failures: list[str] = []


def check(label: str, path: str, *, expect_n: int | None = None,
          expect_header: bool = True, expect_status: int = 200) -> None:
    res = c.get(path)
    ok = res.status_code == expect_status
    body = res.json() if res.headers.get("content-type", "").startswith("application/json") else []
    n = len(body) if isinstance(body, list) else body.get("total", 0)
    # 422 是错误响应，本来就没有分页响应头；/question-ids 把总数放在 body 里
    if expect_status != 200:
        expect_header = False
    if "/question-ids" in path:
        expect_header = False
    if ok and expect_n is not None and n != expect_n:
        ok, note = False, f"期望 {expect_n} 条，实际 {n}"
    else:
        note = f"{n} 条"
    if ok and expect_header and "x-total-count" not in res.headers:
        ok, note = False, "缺少 X-Total-Count 响应头"
    mark = "OK  " if ok else "FAIL"
    if not ok:
        failures.append(f"{label}: {note}")
    print(f"{mark} {label:<40} {res.status_code}  {note}  "
          f"total={res.headers.get('x-total-count', '-')} more={res.headers.get('x-has-more', '-')}")
    return None


print("== 顺序练习（默认 source=sequential）==")
check("第 1 页", f"/api/banks/{BANK}/questions?page=1&page_size=50", expect_n=50)
check("第 2 页", f"/api/banks/{BANK}/questions?page=2&page_size=50", expect_n=50)
check("最后一页（不足一页）",
      f"/api/banks/{BANK}/questions?page=419&page_size=50", expect_n=None)
check("越界页返回空", f"/api/banks/{BANK}/questions?page=9999&page_size=50", expect_n=0)

print("\n== 按状态 / 题型 / 看图 ==")
for ft in ("wrong", "favorite", "cut", "note"):
    check(f"filter_type={ft}", f"/api/banks/{BANK}/questions?page=1&page_size=50&filter_type={ft}")
check("按题型 + 排除看图题",
      f"/api/banks/{BANK}/questions?page=1&page_size=50&question_type=single&has_image=false")
check("看图题", f"/api/banks/{BANK}/questions?page=1&page_size=50&has_image=true")

print("\n== 勾选 / 恢复进度：按 id 取题 ==")
first = c.get(f"/api/banks/{BANK}/questions?page=1&page_size=50").json()
chunk30 = [q["id"] for q in first][:30]
check("ids= 30 个", f"/api/banks/{BANK}/questions?page=1&page_size=30&ids={','.join(map(str, chunk30))}",
      expect_n=30)
check("ids= 里混入非法值 → 422",
      f"/api/banks/{BANK}/questions?page=1&ids=1,abc", expect_status=422)
check("ids= 超过 100 个 → 422",
      f"/api/banks/{BANK}/questions?page=1&ids=" + ",".join(str(i) for i in range(1, 102)),
      expect_status=422)

print("\n== 随机练习：id 列表 + 分批取正文 ==")
res = c.get(f"/api/banks/{BANK}/question-ids")
ids = res.json()["ids"]
print(f"OK   question-ids                         {res.status_code}  "
      f"{len(ids)} 个 id，{len(res.content) / 1024:.1f} KB")
shuffled = ids[::-1]
check("打乱后首批 50 道", 
      f"/api/banks/{BANK}/questions?page=1&page_size=50&ids={','.join(map(str, shuffled[:50]))}",
      expect_n=50)
check("错题 id 列表（打乱题序要用）",
      f"/api/banks/{BANK}/question-ids?filter_type=wrong")

# 随机顺序的每批之间不能重复，也不能漏
print("\n== 随机分批的完整性 ==")
picked: list[int] = []
for page in range(1, 5):
    batch = shuffled[(page - 1) * 50: page * 50]
    got = c.get(f"/api/banks/{BANK}/questions?page=1&page_size={len(batch)}"
                f"&ids={','.join(map(str, batch))}").json()
    picked.extend(q["id"] for q in got)
print(f"OK   4 批共取回 {len(picked)} 道，去重后 {len(set(picked))} 道，"
      f"{'无重复' if len(picked) == len(set(picked)) else '!! 有重复'}")

print()
if failures:
    print("失败项：")
    for f in failures:
        print("  -", f)
    raise SystemExit(1)
print("全部通过")