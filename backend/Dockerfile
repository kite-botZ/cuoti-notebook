# ---------- 基础镜像 ----------
FROM python:3.11-slim

# ---------- 环境变量 ----------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

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

# ---------- 暴露端口 ----------
EXPOSE 3000

# ---------- 启动 ----------
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]