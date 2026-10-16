import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "development")

if APP_ENV == "testing":
    # 测试环境：SQLite 内存库，独立于生产数据
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
else:
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = os.getenv("DB_PORT", "3306")
    DB_NAME = os.getenv("DB_NAME", "cuoti_login")

    DATABASE_URL = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
    )

    engine = create_engine(
        DATABASE_URL,
        echo=(APP_ENV == "development"),
        pool_pre_ping=True,
        # 修复：原本写死 pool_size=3600，而 MySQL 8 的 max_connections 默认只有 151。
        # 压测一上量就会撞 "Too many connections"，而且空闲连接会一直占着服务端内存。
        # 连接池应该按「并发 worker 数 × 每 worker 并发」估算，剩下的靠 max_overflow 兜。
        pool_size=int(os.getenv("DB_POOL_SIZE", "20")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        pool_timeout=float(os.getenv("DB_POOL_TIMEOUT", "10")),
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "3600")),
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """FastAPI 依赖注入：每个请求分配一个 Session。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()