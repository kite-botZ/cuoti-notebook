import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import models  # noqa: F401
from app.cache import cache
from app.db import Base, engine
from app.routes import (
    auth, banks, daily, import_questions, knowledge, practice, stats, upload, user, ai,
)

app = FastAPI(title="错题本 API")

Base.metadata.create_all(bind=engine)

# 图片存储目录：backend/uploads/
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "uploads",
)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 把 /uploads 挂成静态资源
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

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