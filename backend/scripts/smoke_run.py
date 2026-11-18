"""真机冒烟：对**正在运行**的后端发一串真 HTTP 请求，确认改了的东西都还活着。

为什么单独有这个脚本：pytest 是"分支覆盖"，这里要回答的是另一个问题——
"服务真的能起、真的能登录、真的能看图吗"。它不做断言收集，跑完就打印
通过/失败，非 0 退出码即失败。

用法：

    # 1) 先起后端（任选其一）
    python run.py                                  # 本地 :3000，需要 MySQL
    APP_ENV=testing python -m uvicorn app.main:app --port 3011   # 只想冒烟，用内存 SQLite

    # 2) 再跑冒烟（默认打 3000，可用 SMOKE_BASE 改）
    python scripts/smoke_run.py
    SMOKE_BASE=http://127.0.0.1:3011 python scripts/smoke_run.py

注意几点，都是踩过的坑：

- 每次都注册**新用户名**（带时间戳）。固定用户名第二次跑会撞"账号已存在"。
- 注册有按 IP 的限流（默认 10 次/小时），反复跑请重启服务或调大
  `AUTH_REGISTER_IP_MAX`，否则会看到 `操作过于频繁`。
- 图片鉴权在 `APP_ENV=production` 或 `UPLOAD_REQUIRE_AUTH=1` 时才生效，
  冒烟脚本假设是开启的；如果后端是开发默认（关闭），"未登录被拒"那条会失败。
"""
import io
import os
import sys
import time

import httpx

BASE = os.getenv("SMOKE_BASE", "http://127.0.0.1:3000")
SUFFIX = str(int(time.time()))
USER = f"smoke_{SUFFIX}"
USER2 = f"smoke2_{SUFFIX}"
PASSWORD = "smoke123456"
NEW_PASSWORD = "smoke654321"

# 1x1 像素 PNG，够用来验证上传/回读链路
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)

passed, failed = [], []


def check(name, cond, extra=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=20.0) as c:
        r = c.get("/")
        check("服务启动 GET /", r.status_code == 200, r.text[:60])

        r = c.post("/api/register", json={"username": USER, "password": PASSWORD})
        check("注册", r.status_code == 201, r.text[:120])

        r = c.post("/api/login", json={"username": USER, "password": "wrong-pass"})
        check(
            "登录失败不泄露账号是否存在",
            r.status_code == 400 and r.json().get("detail") == "账号或密码错误",
            r.text[:120],
        )

        r = c.post("/api/login", json={"username": USER, "password": PASSWORD})
        check("登录", r.status_code == 200, r.text[:120])
        token = r.json().get("token", "")
        check("下发 token", bool(token))
        check("下发图片 cookie", "cuoti_media" in c.cookies, list(c.cookies.keys()))
        auth = {"Authorization": f"Bearer {token}"}

        r = c.get("/api/user/me", headers=auth)
        check("当前用户", r.status_code == 200, r.text[:120])

        r = c.post("/api/banks", json={"name": "冒烟题库"}, headers=auth)
        check("建题库", r.status_code in (200, 201), r.text[:150])
        bank_id = (r.json() or {}).get("id")

        r = c.get(
            f"/api/banks/{bank_id}/questions",
            params={"page": 1, "page_size": 20},
            headers=auth,
        )
        check(
            "分页响应头",
            r.status_code == 200 and "x-total-count" in r.headers,
            {k: v for k, v in r.headers.items() if k.startswith("x-")},
        )
        r = c.get(f"/api/banks/{bank_id}/questions", headers=auth)
        check(
            "不传 page 时返回全量（X-Page-Size = total）",
            r.status_code == 200 and r.headers.get("x-page-size") == r.headers.get("x-total-count"),
            r.status_code,
        )

        r = c.post(
            "/api/upload",
            files={"file": ("smoke.png", io.BytesIO(PNG), "image/png")},
            headers=auth,
        )
        check("上传图片", r.status_code in (200, 201), r.text[:150])
        url = (r.json() or {}).get("url", "")

        r = c.get(url)
        check("图片：带 cookie 可读", r.status_code == 200 and r.content == PNG, r.status_code)

        anon = httpx.Client(base_url=BASE, timeout=20.0)
        r = anon.get(url)
        check("图片：未登录被拒", r.status_code == 401, r.status_code)
        r = anon.get("/uploads/%2E%2E/app/main.py")
        check("图片：未登录先撞鉴权（不泄露路径是否存在）", r.status_code == 401, r.status_code)
        r = anon.get("/uploads/%2E%2E/app/main.py", headers=auth)
        check("图片：登录后路径穿越被挡", r.status_code == 404, r.status_code)
        r = anon.get(url, headers=auth)
        check("图片：带 Bearer 可读", r.status_code == 200, r.status_code)
        r = anon.get("/uploads/not-exist.png", headers=auth)
        check("图片：缺失文件 404", r.status_code == 404, r.status_code)
        anon.close()

        r = c.post(
            "/api/user/change-password",
            json={"old_password": PASSWORD, "new_password": NEW_PASSWORD},
            headers=auth,
        )
        check("改密码", r.status_code == 200, r.text[:120])
        r = c.get("/api/user/me", headers=auth)
        check("改密后旧 token 立刻失效", r.status_code == 401, r.status_code)

        r = c.post("/api/login", json={"username": USER, "password": PASSWORD})
        check("旧密码已失效", r.status_code == 400, r.status_code)
        r = c.post("/api/login", json={"username": USER, "password": NEW_PASSWORD})
        check("新密码可登录", r.status_code == 200, r.status_code)
        auth2 = {"Authorization": f"Bearer {r.json().get('token', '')}"}

        other = httpx.Client(base_url=BASE, timeout=20.0)
        other.post("/api/register", json={"username": USER2, "password": PASSWORD})
        r = other.post("/api/login", json={"username": USER2, "password": PASSWORD})
        auth3 = {"Authorization": f"Bearer {r.json().get('token', '')}"}
        r = other.get(
            "/api/practice/progress",
            params={"bank_id": bank_id, "source": "bank"},
            headers=auth3,
        )
        check("越权读他人题库进度被拒", r.status_code == 404, r.status_code)
        other.close()

        hits = None
        for i in range(8):
            r = c.post("/api/login", json={"username": USER2, "password": "nope"})
            if r.status_code == 429:
                hits = i + 1
                break
        check("连续登录失败触发 429", hits is not None, f"第 {hits} 次")

        r = c.post("/api/logout")
        check("登出", r.status_code == 200, r.text[:80])
        r = c.get("/api/ai/info", headers=auth2)
        check("AI 信息接口（未装模型也应回 200）", r.status_code == 200, r.text[:120])

    print()
    print(f"通过 {len(passed)}，失败 {len(failed)}")
    if failed:
        print("失败项：")
        for name in failed:
            print("  -", name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
