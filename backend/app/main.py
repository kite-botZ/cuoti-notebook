import mimetypes
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.cache import cache
from app.db import Base, engine, get_db
from app.security import MEDIA_COOKIE
from app.routes import (
    auth, banks, daily, import_questions, knowledge, mastery, practice, rag, stats, upload,
    user, ai,
)

app = FastAPI(title="错题本 API")

Base.metadata.create_all(bind=engine)

# 图片存储目录：backend/uploads/
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "uploads",
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 是否要求登录才能读图片。
# 默认：生产环境要求，开发/测试环境放开（方便直接点开链接看效果、也避免
# 老数据在本地突然全部裂图）。显式设 UPLOAD_REQUIRE_AUTH=0/1 可覆盖。
UPLOAD_REQUIRE_AUTH = os.getenv(
    "UPLOAD_REQUIRE_AUTH", "1" if os.getenv("APP_ENV", "development") == "production" else "0"
) == "1"


def _upload_reader(request: Request, db: Session) -> int | None:
    """识别读图片的人：Authorization 头优先，其次图片专用 cookie。

    返回 user_id，认不出来就返回 None（不抛异常，由调用方决定要不要拦）。
    """
    from app.routes.banks import decode_token  # 延迟导入，避免 main 与 routes 循环

    token = ""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    if not token:
        # <img src> 带不了 Authorization 头，只能靠这个 HttpOnly cookie
        token = request.cookies.get(MEDIA_COOKIE, "")
    if not token:
        return None
    try:
        return decode_token(token, db)
    except HTTPException:
        return None


@app.get("/uploads/{file_path:path}", tags=["uploads"])
def serve_upload(
    file_path: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """受控地提供上传的图片。

    原来这里是 `app.mount("/uploads", StaticFiles(...))`：只要路径能被猜到
    （uuid 有 128 位，猜不到，但**链接会出现在 HTML 里**），任何人、无需登录、
    跨账号都能读。静态挂载没有钩子可以校验身份，所以换成显式路由。

    安全要点：
    - 必须登录（生产环境），或至少带着本服务签发的 token；
    - 路径规范化后必须仍在 UPLOAD_DIR 内（挡 `../` 穿越）；
    - `X-Content-Type-Options: nosniff`，避免把 .png 当脚本执行的老漏洞。
    """
    reader_id = _upload_reader(request, db)
    if reader_id is None and UPLOAD_REQUIRE_AUTH:
        raise HTTPException(status_code=401, detail="请先登录")

    rel = (file_path or "").replace("\\", "/").strip("/")
    if not rel or ".." in rel.split("/"):
        raise HTTPException(status_code=404, detail="文件不存在")

    root = os.path.abspath(UPLOAD_DIR)
    target = os.path.abspath(os.path.join(root, rel))
    if target != root and not target.startswith(root + os.sep):
        raise HTTPException(status_code=404, detail="文件不存在")
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="文件不存在")

    media_type, _ = mimetypes.guess_type(target)
    return FileResponse(
        target,
        media_type=media_type or "application/octet-stream",
        headers={
            "X-Content-Type-Options": "nosniff",
            # 图片内容不会变（文件名是 uuid，不可覆盖），可以放心让浏览器缓存；
            # private 是因为它按用户鉴权，不能让中间代理缓存后发给别人。
            "Cache-Control": "private, max-age=86400",
        },
    )

app.include_router(auth.router)
app.include_router(banks.router)
app.include_router(upload.router)
app.include_router(practice.router)
app.include_router(stats.router)
app.include_router(user.router)
app.include_router(ai.router)
app.include_router(daily.router)
app.include_router(import_questions.router)
app.include_router(knowledge.router)
app.include_router(rag.router)
app.include_router(mastery.router)


@app.get("/")
def root():
    return {"message": "错题本后端已启动"}


@app.get("/api/cache/stats", tags=["ops"])
def cache_stats():
    """缓存命中率。压测和线上巡检都用它取数：

    - `hit` / `miss` / `hit_rate`：进程内统计（本次启动以来）
    - `redis_keyspace_hits` / `redis_hit_rate`：Redis 服务端统计（跨进程、跨重启累计）
    """
    return cache.stats()


@app.post("/api/cache/reset-stats", tags=["ops"])
def reset_cache_stats():
    """压测前清零，保证「优化前 / 优化后」两组数据互不污染。"""
    cache.reset_stats()
    return {"message": "缓存统计已清零", "stats": cache.stats()}