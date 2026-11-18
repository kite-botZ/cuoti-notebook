# ---------- 基础镜像 ----------
# 3.12：与本地/CI 的测试口径一致（tests 在 3.12 上跑）。
# 3.11 也能跑，但"镜像里 3.11、测试跑 3.12"会在依赖升级时悄悄分叉。
FROM python:3.12-slim

# ---------- 环境变量 ----------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ---------- 换 Debian 源为清华源 ----------
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true \
    && sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list 2>/dev/null || true

# ---------- 系统依赖 ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# ---------- 工作目录 ----------
WORKDIR /app

# ---------- 先装 Python 依赖（换清华源）----------
COPY requirements.txt .
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip install --no-cache-dir -r requirements.txt

# ---------- 复制源码 ----------
COPY . .

# ---------- 运行时目录 + 非 root 用户 ----------
# 原来容器以 root 跑。后端会读上传文件、连数据库、还会把 OOM 级别的
# 内存压力留给宿主机，root 权限对这个服务没有任何必要。
# `/app/uploads` 必须在**镜像层**就建好并 chown：compose 里
# `uploads_data:/app/uploads` 这个命名卷第一次创建时是复制镜像里那个目录的
# owner/权限，如果镜像里没有这个目录，卷会归 root，非 root 进程写不进去。
RUN mkdir -p /app/uploads \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

# ---------- 暴露端口 ----------
EXPOSE 3000

# ---------- 启动 ----------
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
