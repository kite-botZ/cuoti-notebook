"""练习页进入时的真实开销：v1（整包） vs 现在（分页 + 按 id 取题）。

对应前端的几条路径：
  sequential  → 第 1 页 50 题
  wrong       → 错题第 1 页
  selected    → 勾选 30 道题
  恢复进度     → 按同样的页数重取（见 Practice.vue 的 loadQuestions）
  random      → id 列表 + 首批 50 道正文

需要 bench MySQL 跑在 3308（cuoti_bench，2 万题）+ 后端跑在 3002。
用法：python scripts/bench_practice_load.py
环境变量 BASE / BANK_ID 可以改目标和题库。

2026-10 实测（20911 题）：
  v1 整包              1476 ms   8236.9 KB
  第 1 页 50 题           8 ms      15.4 KB   时间 1/194  体积 1/535
  错题第 1 页            36 ms      19.4 KB
  勾选 30 道（ids=）     10 ms       8.7 KB
  随机：id 列表          93 ms     111.7 KB
  随机：首批 50 道正文     8 ms      15.4 KB

结果写入 bench-results/practice_load.json。
"""
import json
import os
import time

import httpx

BASE = os.getenv("BASE", "http://127.0.0.1:3002")
BANK = int(os.getenv("BANK_ID", "1"))

c = httpx.Client(base_url=BASE, timeout=300.0)
r = c.post("/api/login", json={"username": "bench_user", "password": "bench123456"})
r.raise_for_status()
c.headers["Authorization"] = f"Bearer {r.json()['token']}"
print("登录成功\n")


def measure(label: str, path: str, repeat: int = 3) -> dict:
    times, size, count = [], 0, 0
    for i in range(repeat):
        t0 = time.perf_counter()
        res = c.get(path)
        res.raise_for_status()
        times.append((time.perf_counter() - t0) * 1000)
        size = len(res.content)
        body = res.json()
        count = body.get("total") if isinstance(body, dict) else len(body)
    times.sort()
    print(f"{label:<34} {times[len(times) // 2]:>8.0f} ms  {size / 1024:>9.1f} KB  {count:>6} 条")
    return {"label": label, "median_ms": round(times[len(times) // 2], 1),
            "bytes": size, "count": count}


out: list[dict] = []

# 1. v1 的做法：整包
out.append(measure("v1 整包（练习页旧行为）", f"/api/banks/{BANK}/questions"))

# 2. 现在的做法
out.append(measure("第 1 页 50 题", f"/api/banks/{BANK}/questions?page=1&page_size=50"))
out.append(measure("第 1 页 50 题（热缓存）", f"/api/banks/{BANK}/questions?page=1&page_size=50"))
out.append(measure("错题第 1 页", f"/api/banks/{BANK}/questions?page=1&page_size=50&filter_type=wrong"))

# 3. 按 id 取题（勾选 / 恢复进度）
ids = c.get(f"/api/banks/{BANK}/questions?page=1&page_size=50").json()
chunk = [q["id"] for q in ids][:30]
out.append(measure(
    "勾选 30 道（ids=）",
    f"/api/banks/{BANK}/questions?page=1&page_size=30&ids={','.join(map(str, chunk))}",
))

# 4. 随机练习两步
out.append(measure("随机：id 列表（整库）", f"/api/banks/{BANK}/question-ids", repeat=2))
out.append(measure("随机：首批 50 道正文", f"/api/banks/{BANK}/questions?page=1&page_size=50"))

base = out[0]
print("\n对比（以 v1 整包为 1）：")
for row in out[1:]:
    print(f"  {row['label']:<32} 时间 1/{base['median_ms'] / row['median_ms']:.0f}"
          f"   体积 1/{base['bytes'] / row['bytes']:.0f}")

path = r"E:\dswork\bench-results\practice_load.json"
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"\n已写入 {path}")