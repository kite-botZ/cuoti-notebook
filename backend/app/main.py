import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import models  # noqa: F401
from app.db import Base, engine
from app.routes import auth, banks, upload, practice, stats,user,ai,daily

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


@app.get("/")
def root():
    return {"message": "错题本后端已启动"}