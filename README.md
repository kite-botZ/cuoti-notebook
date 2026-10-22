# 错题本 · Agentic AI 学习平台

> 一个可以自己出题、自动判分、自动收集错题，并用**本地大模型**讲题的刷题系统。
> 前后端分离，数据全部留在自己机器上。

<p>
  <img alt="python" src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white">
  <img alt="fastapi" src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white">
  <img alt="vue" src="https://img.shields.io/badge/Vue-3.5-4FC08D?logo=vuedotjs&logoColor=white">
  <img alt="mysql" src="https://img.shields.io/badge/MySQL-8.0-4479A1?logo=mysql&logoColor=white">
  <img alt="redis" src="https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white">
  <img alt="docker" src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white">
</p>

<!--
🔗 如果有线上地址，把下面这行注释去掉并填上 —— 这是 README 里最值钱的一行，
   别人更愿意点开链接，而不是照文档在自己电脑上装环境：

   **在线试用：<http://你的地址>**（账号自己注册即可）
-->

<!--
📷 建议放 2~3 张截图（HTML 注释不会渲染，放好图后把这段删掉）：
   ![登录页](docs/screenshots/login.png)
   ![题库与批量导入](docs/screenshots/bank.png)
   ![AI 解析](docs/screenshots/ai.png)
   截图放 docs/screenshots/ 下。
-->

---

## 5 分钟跑起来

### 方式一：Docker（推荐，四条命令）

```bash
# 1. 拉代码
git clone https://github.com/kite-botZ/cuoti-notebook.git
cd cuoti-notebook

# 2. 准备配置（默认值就能跑，不用改）
cp .env.example .env

# 3. 一键启动（MySQL + Redis + 后端 + 前端）
docker compose up -d --build

# 4. 确认四个容器都起来了
docker compose ps
```

浏览器打开 **<http://localhost:8080>** → 点「注册」建个账号 → 开始用。

| 地址 | 说明 |
|---|---|
| <http://localhost:8080> | 前端页面 |
| <http://localhost:3000/docs> | 后端接口文档（Swagger，可直接调试） |

> ⏱ **首次启动要构建镜像，约 3~5 分钟**（下载基础镜像 + 装依赖）。之后再启动是秒级。
> 停掉：`docker compose down`（加 `-v` 会连数据库一起删除）。

---

### 方式二：本地开发模式（不用 Docker）

需要本机已有 **Python 3.11+ / Node 22+ / MySQL 8**。

```bash
# 后端
cd backend
python -m venv .venv && .venv\Scripts\activate     # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                # 填上你的 MySQL 密码
python run.py                                       # http://localhost:3000/docs

# 前端（另开一个终端）
cd frontend
npm install
npm run dev                                         # http://localhost:5173
```

前端开发时把 `/api` 和 `/uploads` 代理到 `localhost:3000`（见 `vite.config.ts`），
要改后端地址只改 `frontend/.env.development` 里的 `VITE_API_TARGET`。

> Redis 是可选的：不装也能跑，缓存层会自动降级为直接查库（接口慢一些）。
> 想彻底关掉缓存，在 `backend/.env` 里设 `CACHE_DISABLED=1`。

---

## ✨ 功能

### 题库与题目

- 题库增删改查，按学科分类；每个账号只看得到自己的题库（按 `user_id` 隔离，越权返回 404）
- 支持 **6 种题型**：单选、多选、判断、填空、简答、计算
- **批量导入**：JSON / Excel / Word / PDF 四种格式，共用一套解析层
  - 落库前按「题干 + 题型 + 选项」做库内与文件内**双重去重**，同一文件重复导入不会产生重复题
  - **逐行容错**：个别行格式不对不会让整个文件失败，好行照常入库
  - 返回**结构化错误清单**（第几行、什么原因），改完只需要重传坏行
- 支持题干和答案里插入图片（手写草稿、试卷拍照）

### 答题与判分

- 单选 / 判断直接比字母；多选**答案顺序无关**（`AC` = `CA`）
- 填空 / 简答 / 计算做**宽松匹配**：去掉空格和标点再比，避免「北京」vs「北京市。」这种误判
- 答案里带图片的题目自动转为**自评**，不计入错题
- 每次作答都留历史记录（`answer_attempts` 只增不改）

### 错题本

- 答错自动进错题本，累计 `wrong_count`
- 支持**收藏**、**写笔记**、**斩题**（标记为已掌握，不再出现在练习里）、**批量斩题**
- 按「错题 / 收藏 / 斩题 / 有笔记」筛选

### AI 讲题（可本地可云端，默认本地）

- **AI 解析**：针对当前题目生成讲解，SSE 流式输出有打字机效果，支持 LaTeX 公式渲染
- **AI 助手**：基于 Function Calling 实现了两个工具，参考 ReAct 思路让模型自己决定调不调工具
  - `search_wrong_questions` —— 查你的错题（"我之前错过哪些类似的题？"）
  - `grade_calculation` —— 批改计算 / 简答 / 填空题（"我算的是 96，对吗？"）
- 解析结果缓存到 Redis，**同一道题再问不会重复调用模型**
- 模型服务可切换：`LLM_PROVIDER=ollama`（本地跑，数据不出机器）或
  `bailian`（阿里云百炼，OpenAI 兼容模式，按量计费）。两者共用同一套调用代码，
  切换不用改业务逻辑

### 讲义知识库（RAG）

页面在 **`/knowledge`**：上传讲义、看切分结果、看检索分数、给题目打知识点。

- **上传解析**：支持 PDF / DOCX / Markdown / TXT
  - PDF 走**双引擎**：先用 pypdfium2 抽，抽不出可用文本再退回 pdfminer
  - 抽完过一道**可读性闸门**，用一张高频字表算「高频字占中文字符的比例」：
    - 高频字占比 < 15%、或 `(cid:)` 编码占比 > 2% → 判定 `garbage`，**直接拦截**
      并说明「这种 PDF 通常是字体子集缺 ToUnicode 映射，需要 OCR 或换文字版材料」
    - 高频字占比 15% ~ 30% → 判定 `suspect`，放行但附一条「检索效果可能不好」的警告
    - 文本不足 30 字 → `too_short`；中文字符不足 20 个（英文材料）→ `no_cjk`，不做中文判定
  - 扫描件（整页是图片、抽不出文字）会被明确拒绝并提示先做 OCR，
    而不是静默入库一堆空片段
- **切分**：按段落聚合成块，带重叠窗口，保留章节 / 页码，切完可在页面逐块查看
- **检索**：BM25（中文按 2-gram，不依赖分词词典）+ 向量余弦，**加权混合**
  - 权重 α 可在页面上拖动，`α = 0` 是纯关键词、`α = 1` 是纯语义
  - 检索结果把 `score` / `bm25_score` / `vector_score` / `coverage` 四项分数
    都返回并画成条形，能直接看出混合检索是不是真比单路好（调参用）
  - 有词命中率下限过滤，避免把几乎不相关的片段塞进 prompt
- **引用出处**：AI 讲解引用的片段会带上「来自哪本讲义、第几页」
- **知识点自动打标**：大模型读题目归纳知识点，写入关联表；支持
  `dry_run` 先看提示词再决定跑不跑，默认只处理还没打标的题，不重复烧推理

> **关于向量**：项目没有引入向量数据库。片段量级在万级以内，向量直接以 JSON
> 存在 MySQL 里、在 Python 侧算余弦就够了；多引一个需要单独部署和运维的组件，
> 换来的收益在这个数据量下不成立。**代价是全量扫描**，所以它适合万级片段，
> 不适合百万级——真到那个量级应该换成 pgvector 或 Milvus。

> **关于 embedding**：向量检索需要 embedding 模型。没配（或模型服务连不上）时
> 入库会**自动退化成只建 BM25 索引**，检索仍然可用，页面会标出「仅 BM25 索引」
> 和「向量覆盖率 0%」，不会直接报错。

### 学习统计

- 用 ECharts 展示答题量、正确率、错题分布等学习报告

### 账号体系

- 注册 / 登录 / JWT 鉴权 / 找回密码（验证码校验 + 一次性重置凭证）
- 密码用 bcrypt 加盐哈希存储；旧明文密码登录时自动升级成哈希

---

## 🧱 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 后端 | **Python 3.11 · FastAPI** | 原生异步框架，自动生成 OpenAPI 文档 |
| ORM | **SQLAlchemy 2.x · PyMySQL** | 声明式模型，启动时 `create_all` 自动建表 |
| 数据库 | **MySQL 8** | `utf8mb4`，外键 `ON DELETE CASCADE` |
| 缓存 | **Redis 7** | AI 解析结果缓存、题目列表缓存、防击穿分布式锁 |
| 鉴权 | **PyJWT · bcrypt** | Bearer Token，`HTTPBearer` 依赖注入 |
| 校验 | **Pydantic v2** | 请求体校验，统一 422 错误格式 |
| 导入解析 | **openpyxl · python-docx · pdfplumber** | 分别解析 Excel / Word / PDF |
| RAG 解析 | **pypdfium2 · pdfminer.six** | 讲义 PDF 双引擎解析 + 可读性闸门 |
| RAG 检索 | **自实现 BM25(2-gram) + 余弦混合** | 不依赖分词词典和向量数据库 |
| AI | **Ollama / 阿里云百炼** | 同一套接口，`LLM_PROVIDER` 切换；SSE 流式返回 |
| 前端 | **Vue 3 · TypeScript · Vite** | Composition API，`<script setup>` |
| 图表 / 公式 | **ECharts · KaTeX** | 学习报告图表、数学公式渲染 |
| 编排 | **Docker Compose · Nginx** | 四容器，Nginx 反代 + 静态托管 |

<details>
<summary><b>为什么用 PyMySQL 而不是 mysqlclient？</b></summary>

PyMySQL 是纯 Python 实现，不需要编译，`pip install` 直接可用，
镜像里也不用装 `gcc` / `libmysqlclient-dev` 这些编译依赖。
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
│   │   ├── knowledge.py        # 知识点：打标提示词、解析、关联表写入
│   │   ├── llm.py              # 模型服务抽象：Ollama / 百炼 同一套接口
│   │   ├── rag/                # 讲义解析 / 切分 / 向量化 / 混合检索
│   │   ├── security.py         # JWT 密钥与算法（集中配置，生产环境缺密钥直接启动失败）
│   │   ├── agent/              # ReAct 循环 + Function Calling 工具
│   │   └── routes/             # auth / banks / import_questions / ai / rag / knowledge ...
│   ├── tests/                  # pytest 接口测试
│   ├── scripts/                # 数据集生成 + 压测 + 冒烟脚本
│   ├── requirements.txt
│   └── Dockerfile
│
└── frontend/
    ├── src/
    │   ├── views/              # Login / Home / Bank / Practice / Stats / Knowledge ...
    │   ├── components/         # AiAssistant 等通用组件
    │   ├── api/request.ts      # axios 实例（自动带 token、统一错误处理）
    │   └── router/index.ts     # 路由 + 登录守卫
    ├── nginx.conf              # 反代配置（含 SSE 关缓冲、上传大小放开）
    └── Dockerfile
```

---

## ⚙️ 配置项

Docker 用根目录 `.env`；本地开发用 `backend/.env`（完整列表见 `backend/.env.example`）。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DB_PASSWORD` | — | MySQL root 密码，**compose 部署必填** |
| `DB_NAME` | `cuoti_login` | 数据库名，首次启动自动创建 |
| `DB_HOST` / `DB_PORT` | `127.0.0.1` / `3306` | 容器内由 compose 覆盖成 `db:3306` |
| `DB_POOL_SIZE` | `20` | 连接池大小。**别超过 MySQL 的 `max_connections`（默认 151）** |
| `JWT_SECRET_KEY` | — | 签名密钥。**`APP_ENV=production` 时必填**，缺失会直接启动失败 |
| `JWT_EXPIRE_SECONDS` | `3600` | Token 有效期 |
| `RESET_TICKET_SECONDS` | `600` | 验证码校验通过后，重置密码凭证的有效期 |
| `AUTH_ECHO_CODE` | 开发 `1` / 生产 `0` | 是否把验证码放进 `/api/send-code` 响应里 |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | 缓存地址，容器内是 `redis://redis:6379/0` |
| `CACHE_DISABLED` | `0` | 设 `1` 彻底关闭缓存 |
| `CACHE_EXPLAIN_TTL` | `86400` | AI 解析缓存时长（秒） |
| `CACHE_QLIST_TTL` | `300` | 题目列表缓存时长（秒） |
| `IMPORT_CHUNK_SIZE` | `500` | 导入时每多少条一个事务 |
| `AI_API_BASE` | `http://localhost:11434` | Ollama 地址 |
| `AI_MODEL` | `qwen2.5:7b` | 模型名，必须和 `ollama list` 里的一致 |
| `LLM_PROVIDER` | `ollama` | `ollama` 本地 / `bailian` 阿里云百炼 |
| `EMBED_MODEL` | `bge-m3` | 本地向量模型，用之前要 `ollama pull bge-m3` |
| `BAILIAN_API_KEY` | — | 百炼 key。**只写在 `.env` 里，不要提交、不要贴聊天** |
| `BAILIAN_MODEL` / `BAILIAN_EMBED_MODEL` | `qwen-plus` / `text-embedding-v3` | 百炼的对话 / 向量模型 |
| `BAILIAN_EMBED_BATCH` | `10` | 百炼向量接口单次条数上限，超了会报错 |
| `RAG_TOP_K` | `5` | 检索默认召回条数 |
| `RAG_ALPHA` | `0.5` | 混合检索里向量的权重（`0` 纯 BM25、`1` 纯向量） |
| `RAG_MIN_COVERAGE` | `0.2` | 词命中率下限，低于它的片段不返回 |
| `RAG_MAX_DOC_SIZE` | `31457280`（30MB） | 讲义上传大小上限，**要和 Nginx 的 `client_max_body_size` 对齐** |
| `TAG_BATCH_SIZE` | `10` | 自动打标时一次请求让模型处理几道题 |

---

## 🤖 启用 AI 功能（可选）

不装 Ollama 也能正常用其它功能，只是「AI 解析 / AI 助手」两个按钮会报错。

```bash
# 1. 安装 Ollama：https://ollama.com/download
# 2. 拉一个模型（4B 左右在普通笔记本上够用）
ollama pull qwen2.5:7b        # 或 gemma3:4b / llama3.2:3b，更省内存

# 3. 确认服务在跑
curl http://localhost:11434/api/tags
```

然后改 `.env` 里的两行：

```env
AI_API_BASE=http://host.docker.internal:11434
AI_MODEL=qwen2.5:7b
```

改完重启后端：`docker compose restart backend`。

> 容器访问宿主机的 Ollama 走 `host.docker.internal`。
> 这个域名 Docker Desktop 自带；Linux 上本项目已经在 `docker-compose.yml`
> 里用 `extra_hosts: host-gateway` 映射好了，不用再改。

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
脚本在 `backend/scripts/`，可以自己复现：

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

共 **238 个**接口测试，覆盖认证与账号安全、题库 CRUD、答题判分、越权访问、
批量导入、分页与缓存一致性、RAG 解析与混合检索、知识点打标。
测试用 SQLite 内存库，不会污染你的 MySQL。

另有一个**需要真实后端在跑**的端到端冒烟脚本，把前端页面用到的知识库接口
逐个字段打一遍（pytest 是进程内 TestClient，测不出「页面拿到的字段形状对不对」）：

```bash
# 先把后端跑起来，然后
cd backend
python scripts/smoke_knowledge_api.py --base-url http://127.0.0.1:3000
```

它会注册一个带随机后缀的测试账号、建题库、上传一份 Markdown 讲义，走完
「列表 → 切分片段 → 检索 → 知识点增删 → 覆盖率 → 打标预览 → 删除级联」，
并覆盖三类失败路径（不支持的格式 / 空文件 / 解析不出文字的空白文档）。
默认跑完清理自己上传的文档；加 `--keep` 可以留着打开页面看。

> ⚠️ 它会往 `--base-url` 指向的**当前数据库**写数据，别在线上跑。

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

先看后端日志：`docker compose logs backend --tail 50`。
最常见是 MySQL 还没 ready 后端就启动了——等十几秒刷新，
或者 `docker compose restart backend`。
</details>

<details>
<summary><b>点「AI 解析」报错连不上 Ollama</b></summary>

1. 本机确认服务在跑：`curl http://localhost:11434/api/tags`
2. 确认容器能访问宿主机：
   `docker compose exec backend curl -s http://host.docker.internal:11434/api/tags`
3. 确认 `AI_MODEL` 和 `ollama list` 里的名字**完全一致**（带 `:tag`）
</details>

<details>
<summary><b>批量导入点「开始导入」没反应 / 提示 404</b></summary>

确认后端代码是最新的（导入接口在 `backend/app/routes/import_questions.py`），
然后 `docker compose up -d --build` 重新构建一次。
</details>

<details>
<summary><b>上传图片或导入大文件失败</b></summary>

Nginx 默认只允许 1MB 请求体。本项目 `frontend/nginx.conf` 里已经设了
`client_max_body_size 20m`（图片限制 5MB、导入限制 10MB）。
如果你用的是自己的 Nginx，记得同步这个配置。
</details>

<details>
<summary><b>中文出现乱码</b></summary>

数据库必须是 `utf8mb4`。`docker-compose.yml` 已通过
`--character-set-server=utf8mb4` 指定；如果用外部 MySQL，
建库时加 `CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci`。
</details>

---

## 📄 License

个人学习项目，未指定开源协议。想用请先开个 issue 说一声。
