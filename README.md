# 错题本 · Agentic AI 学习平台

> 一个可以自己出题、自动判分、自动收集错题，并用**本地大模型**讲题的刷题系统。
> 前后端分离，四条命令跑起来，数据全部留在自己电脑上。

<p>
  <img alt="python" src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white">
  <img alt="fastapi" src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white">
  <img alt="vue" src="https://img.shields.io/badge/Vue-3.5-4FC08D?logo=vuedotjs&logoColor=white">
  <img alt="mysql" src="https://img.shields.io/badge/MySQL-8.0-4479A1?logo=mysql&logoColor=white">
  <img alt="redis" src="https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white">
  <img alt="docker" src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white">
</p>

---

<!--
📷 建议在这里放 2~3 张截图（HTML 注释不会渲染，你放好图后把这段删掉）：
   ![登录页](docs/screenshots/login.png)
   ![题库与导入](docs/screenshots/bank.png)
   ![AI 解析](docs/screenshots/ai.png)
   截图放在 docs/screenshots/ 下，然后删掉这段注释。
-->

## 5 分钟跑起来

只需要装好 [Docker Desktop](https://www.docker.com/products/docker-desktop/)，然后：

```bash
# 1. 拉代码
git clone https://github.com/kite-botZ/cuoti-notebook.git
cd cuoti-notebook

# 2. 准备配置（用默认值就能跑，不用改）
cp .env.example .env

# 3. 一键启动（MySQL + Redis + 后端 + 前端 四个容器）
docker compose up -d --build

# 4. 看日志确认都起来了
docker compose ps
```

然后打开 **<http://localhost:8080>** → 点「注册」建个账号 → 开始用。

| 地址 | 说明 |
|---|---|
| <http://localhost:8080> | 前端页面 |
| <http://localhost:3000/docs> | 后端接口文档（Swagger，可以直接调试） |
| `localhost:3000` | 后端 API |

> ⏱ **首次启动需要构建镜像，大约 3~5 分钟**（要下载基础镜像）。
> 之后再启动是秒级：`docker compose up -d`。
>
> 想停掉：`docker compose down`（加 `-v` 会连数据库一起删掉）。

<details>
<summary><b>方式二：本地开发模式（不想用 Docker）</b></summary>

需要本机已有 **Python 3.11+ / Node 22+ / MySQL 8 / Redis 7**。

```bash
# 后端
cd backend
python -m venv .venv && .venv\Scripts\activate     # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                # 填上你的 MySQL 密码
python run.py                                       # http://localhost:3000

# 前端（另开一个终端）
cd frontend
npm install
npm run dev                                         # http://localhost:5173
```

本地开发时前端把 `/api` 和 `/uploads` 代理到 `localhost:3000`（见 `vite.config.ts`），
所以要改后端地址只改 `frontend/.env.development` 里的 `VITE_API_TARGET`。

Redis 是可选的：不装也能跑，缓存层会自动降级为直接查库（接口会慢一些）。
想彻底关掉缓存，在 `backend/.env` 里设 `CACHE_DISABLED=1`。

</details>

---

## ✨ 功能

### 题库与题目

- 题库增删改查，按学科分类，每个账号只看得到自己的题库（按 `user_id` 隔离，越权返回 404）
- 支持 **6 种题型**：单选、多选、判断、填空、简答、计算
- **批量导入**：JSON / Excel / Word / PDF 四种格式，共用一套解析层
  - 落库前按「题干 + 题型 + 选项」做库内与文件内**双重去重**，同一文件重复导入不会产生重复题
  - 逐行容错：个别行格式不对不会让整个文件失败，好行照常入库
  - 返回**结构化错误清单**（第几行、什么原因），改完只需重传坏行
- 支持题干和答案里插入图片（手写草稿、试卷拍照）

### 答题与判分

- 单选 / 判断直接比字母；多选**答案顺序无关**（`AC` = `CA`）
- 填空 / 简答 / 计算做**宽松匹配**：去掉空格和标点再比，避免「北京」vs「北京市。」这种误判
- 答案里带图片的题目自动转为**自评**，不计入错题
- 每次作答都留历史记录（`answer_attempts` 只增不改）

### 错题本

- 答错自动进错题本，累计 `wrong_count`
- 支持**收藏**、**写笔记**、**斩题**（标记为已掌握，不再出现在练习里）
- 支持**批量斩题**
- 按「错题 / 收藏 / 斩题 / 有笔记」筛选

### AI 讲题（本地大模型，数据不出机器）

- **AI 解析**：针对当前题目生成讲解，SSE 流式输出，有打字机效果，支持 LaTeX 公式渲染
- **AI 助手**：基于 Function Calling 实现了两个工具，参考 ReAct 思路让模型自己决定调不调工具
  - `search_wrong_questions` —— 查你的错题（"我之前错过哪些类似的题？"）
  - `grade_calculation` —— 批改计算 / 简答 / 填空题（"我算的是 96，对吗？"）
- 解析结果会缓存到 Redis，**同一道题再问不会重复调用模型**

### 学习统计

- 用 ECharts 展示答题量、正确率、错题分布等学习报告

### 账号体系

- 注册 / 登录 / JWT 鉴权 / 找回密码（验证码走邮箱）
- 密码用 bcrypt 加盐哈希存储

---

## 🧱 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 后端 | **Python 3.11 · FastAPI** | 原生异步框架，自动生成 OpenAPI 文档 |
| ORM | **SQLAlchemy 2.x · PyMySQL** | 声明式模型，`Base.metadata.create_all` 自动建表 |
| 数据库 | **MySQL 8** | `utf8mb4`，外键 `ON DELETE CASCADE` |
| 缓存 | **Redis 7** | AI 解析结果缓存、题目列表缓存、防击穿分布式锁 |
| 鉴权 | **PyJWT · bcrypt** | Bearer Token，`HTTPBearer` 依赖注入 |
| 校验 | **Pydantic v2** | 请求体校验，统一 422 |
| 导入解析 | **openpyxl · python-docx · pdfplumber** | 分别解析 Excel / Word / PDF |
| AI | **Ollama** | 本地跑大模型，SSE 流式返回 |
| 前端 | **Vue 3 · TypeScript · Vite** | Composition API，`<script setup>` |
| 图表 / 公式 | **ECharts · KaTeX** | 学习报告图表、数学公式渲染 |
| 部署 | **Docker Compose · Nginx** | 四容器编排，Nginx 反代 + 静态托管 |

<details>
<summary><b>为什么用 PyMySQL 而不是 mysqlclient？</b></summary>

PyMySQL 是纯 Python 实现，不需要编译，`pip install` 就能用，镜像也不用装
`gcc` / `libmysqlclient-dev` 这些编译依赖。（当前 Dockerfile 里还留着这几个包，
是历史遗留，去掉可以再快一点。）

</details>

---

## 📁 目录结构

```
cuoti-notebook/
├── docker-compose.yml          # MySQL + Redis + 后端 + 前端 四容器编排
├── .env.example                # compose 用的环境变量模板
│
├── backend/
│   ├── app/
│   │   ├── main.py             # 入口：注册路由、建表、缓存统计接口
│   │   ├── db.py               # 引擎 / Session / Base / get_db
│   │   ├── models.py           # SQLAlchemy 模型
│   │   ├── cache.py            # Redis 缓存层（降级、版本号失效、防击穿）
│   │   ├── importer.py         # 四种格式的题目解析器
│   │   ├── agent/              # ReAct 循环 + Function Calling 工具
│   │   └── routes/             # auth / banks / import_questions / ai / practice ...
│   ├── tests/                  # pytest 接口测试
│   ├── scripts/                # 数据集生成 + 压测脚本
│   ├── requirements.txt
│   └── Dockerfile
│
└── frontend/
    ├── src/
    │   ├── views/              # Login / Home / Bank / Practice / Stats ...
    │   ├── components/         # AiAssistant 等通用组件
    │   ├── api/request.ts      # axios 实例（自动带 token、统一错误处理）
    │   └── router/index.ts     # 路由 + 登录守卫
    ├── nginx.conf              # 生产环境的反代配置（含 SSE 关缓冲）
    └── Dockerfile
```

---

## ⚙️ 配置项

后端所有配置都走环境变量，完整列表见 [`backend/.env.example`](backend/.env.example)。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `3306` | MySQL 地址（容器里由 compose 覆盖成 `db:3306`） |
| `DB_NAME` | `cuoti_login` | 数据库名，不存在会自动建表 |
| `DB_POOL_SIZE` | `20` | 连接池大小。**别超过 MySQL 的 `max_connections`（默认 151）** |
| `JWT_SECRET_KEY` | — | 必填，签名密钥 |
| `JWT_EXPIRE_SECONDS` | `3600` | Token 有效期 |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | 缓存地址 |
| `CACHE_DISABLED` | `0` | 设 `1` 彻底关闭缓存 |
| `CACHE_EXPLAIN_TTL` | `86400` | AI 解析缓存时长（秒） |
| `CACHE_QLIST_TTL` | `300` | 题目列表缓存时长（秒） |
| `IMPORT_CHUNK_SIZE` | `500` | 导入时每多少条一个事务 |
| `AI_API_BASE` | `http://localhost:11434` | Ollama 地址 |
| `AI_MODEL` | `qwen2.5:7b` | 模型名，要和 `ollama list` 一致 |

---

## 🤖 启用 AI 功能（可选）

不装 Ollama 也能正常用其它功能，只是「AI 解析 / AI 助手」两个按钮会报错。

```bash
# 1. 安装 Ollama：https://ollama.com/download
# 2. 拉一个模型（4B 左右的模型在普通笔记本上够用）
ollama pull qwen2.5:7b        # 或者 gemma3:4b / llama3.2:3b，更省显存

# 3. 确认服务在跑
curl http://localhost:11434/api/tags
```

然后改 `.env` 里的两行：

```env
AI_API_BASE=http://host.docker.internal:11434   # Linux 改成 http://172.17.0.1:11434
AI_MODEL=qwen2.5:7b
```

改完重启后端容器：`docker compose restart backend`。

> 容器里访问宿主机的 Ollama 走 `host.docker.internal`；
> 如果你是 Linux 并且 `host.docker.internal` 不通，在 `docker-compose.yml` 的
> `backend` 服务下加一行 `extra_hosts: ["host.docker.internal:host-gateway"]`。

---

## 📊 性能

用 2 万题的题库做过一轮压测（单机，客户端和服务端在同一台机器上）：

| 场景 | 优化前 | 优化后 |
|---|---|---|
| 题目列表接口 P95 | 18.4s / 8.1MB | 949ms / 8.5KB（命中缓存 66ms） |
| AI 解析单次 | 19.2s | 30ms（命中缓存） |
| 同题 5 并发模型调用 | 5 次 / 210s | 1 次 / 21.6s |
| 含 8% 脏行的 1000 题导入 | 0%（整包失败） | 91.9%（附错误清单） |

主要手段：**游标分页 + 联合索引 + Redis 内容缓存（版本号失效）+ `SET NX` 防击穿**。
压测脚本在 `backend/scripts/`，可以自己复现：

```bash
cd backend
python scripts/seed_data.py --questions 20000      # 造数据集
python scripts/bench_api.py --base-url http://127.0.0.1:3000 --bank-id 1
```

---

## 🧪 测试

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

共 102 个接口测试，覆盖认证、题库 CRUD、答题判分、越权访问、批量导入、
分页与缓存一致性。测试用 SQLite 内存库，不会污染你的 MySQL。

---

## ❓ 常见问题

<details>
<summary><b>`docker compose up` 报错 "MYSQL_ROOT_PASSWORD is required"</b></summary>

没建 `.env`。执行 `cp .env.example .env` 再启动。
</details>

<details>
<summary><b>8080 / 3000 端口被占用</b></summary>

改 `docker-compose.yml` 里对应服务的端口映射，比如把 `"8080:80"` 改成 `"8081:80"`，
然后访问 <http://localhost:8081>。
</details>

<details>
<summary><b>页面能打开，但接口全部 404 / 登录不上</b></summary>

先看后端是不是真的起来了：`docker compose logs backend --tail 50`。
最常见的原因是 MySQL 还没 ready 后端就启动了——等十几秒再刷新，
或者 `docker compose restart backend`。
</details>

<details>
<summary><b>点「AI 解析」报错连不上 Ollama</b></summary>

1. 本机确认服务在跑：`curl http://localhost:11434/api/tags`
2. 确认容器能访问宿主机：Linux 用户看上面「启用 AI 功能」里的 `extra_hosts` 说明
3. 确认 `AI_MODEL` 和 `ollama list` 里的名字**完全一致**（带 `:tag`）
</details>

<details>
<summary><b>批量导入点了没反应 / 提示 404</b></summary>

确认后端代码是最新的（导入接口在 `backend/app/routes/import_questions.py`）。
`docker compose up -d --build` 重新构建一次。
</details>

<details>
<summary><b>中文出现乱码</b></summary>

数据库必须是 `utf8mb4`。`docker-compose.yml` 里已经通过
`--character-set-server=utf8mb4` 指定了；如果你用的是自己的 MySQL，
建库时加 `CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci`。
</details>

---

## 📄 License

个人学习项目，未指定开源协议。如果你想用，请先开 issue 说一声。
