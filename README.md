# 错题本 · 智能刷题系统

> 一个可以自己出题、自动判分、自动收集错题，用**本地大模型**讲题，
> 并按**知识点掌握度**决定下一题刷什么的刷题系统。
> 前后端分离，数据全部留在自己机器上。

<p>
  <img alt="python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="fastapi" src="https://img.shields.io/badge/FastAPI-0.143-009688?logo=fastapi&logoColor=white">
  <img alt="vue" src="https://img.shields.io/badge/Vue-3.5-4FC08D?logo=vuedotjs&logoColor=white">
  <img alt="mysql" src="https://img.shields.io/badge/MySQL-8.0-4479A1?logo=mysql&logoColor=white">
  <img alt="redis" src="https://img.shields.io/badge/Redis-5%2B-DC382D?logo=redis&logoColor=white">
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

需要本机已有 **Python 3.12（3.11+ 也可以） / Node 22+ / MySQL 8**。

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

### 认知诊断与自适应选题

系统不只用对错打分，还会**推断你每个知识点大概会到什么程度**，然后据此出题。

- **模型**：BKT（贝叶斯知识追踪），四个参数 `p_init=0.30`、`p_learn=0.15`、
  `p_slip=0.10`、`p_guess=0.25`。每答一题先按对错做贝叶斯后验，
  再把后验向"学会了"方向迁移。纯数学实现（`backend/app/bkt.py`），不碰数据库，
  所以能单独测——44 条测试盯着它的单调性、饱和值和边界。
- **显示档位**：熟练 ≥0.90 / 基本掌握 ≥0.72 / 薄弱 ≥0.45 / 未掌握。
  这几个数是按模型真实轨迹反推标定出来的（连对是
  `0.30 → 0.666 → 0.896 → 0.973 → 0.99`），不是随手分的区间。
- **选题策略**：`explore + 0.5 × exploit`
  - `explore`（按练习次数衰减）保证没见过的知识点优先被覆盖；
  - `exploit`（按错题数累加）保证错得多的知识点反复出现；
  - 多个目标知识点之间轮转，不会一直卡在同一个知识点上刷。
- **每道题都说明理由**：前端会显示"主考「加法运算」（掌握度 0.30 · 未掌握）"，
  知识点题目不够时也会明说"用没做过的题补齐覆盖面"，而不是悄悄塞一道无关的题。
- **交卷即反馈**：答题接口直接回传 `mastery_changes`，页面显示这道题让哪个
  知识点涨了多少、有没有掉档。

> **关于 BKT 的三个反直觉行为**（都写进了 `bkt.py` 的文档字符串，免得被当成 bug 改掉）：
> 1. **一直答错不会掉到 0**，会稳定在 **0.173**。答错只能说明"这次没做对"，
>    不能推断"永远不会"，这是有意的；
> 2. **一直答对会饱和在 0.99**，连对四题就到顶。不是 1，保留"还会有意外"；
> 3. **单个 `p_guess` 区分不了"真会"和"蒙对"**，对选择题偏乐观、对填空偏悲观。
>    这是模型本身的已知上限，不是实现错误。
>
> 参数还必须满足 `1 - p_slip > p_guess` 才可辨识，`validate()` 会直接拒绝
> 不合法的组合——否则"掌握度上升"可能只是参数自己编出来的。

> **重置不等于删记录**：`DELETE /banks/{id}/mastery` 只把掌握度打回初始值，
> 作答历史保留。诊断可以重来，但不会篡改"你确实做过这些题"这件事。

### 账号体系

- 注册 / 登录 / JWT 鉴权 / 找回密码（验证码校验 + 一次性重置凭证）
- 密码用 bcrypt 加盐哈希存储；旧明文密码登录时自动升级成哈希

---

## 🧱 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 后端 | **Python 3.12 · FastAPI** | 原生异步框架，自动生成 OpenAPI 文档（代码兼容 3.11+） |
| ORM | **SQLAlchemy 2.x · PyMySQL** | 声明式模型，启动时 `create_all` 自动建表 |
| 数据库 | **MySQL 8** | `utf8mb4`，外键 `ON DELETE CASCADE` |
| 缓存 | **Redis（5.x 起可用）** | AI 解析结果缓存、题目列表缓存、防击穿分布式锁；显式走 RESP2，不用 Redis 6 才有的 `HELLO` |
| 鉴权 | **PyJWT · bcrypt** | Bearer Token，`HTTPBearer` 依赖注入 |
| 校验 | **Pydantic v2** | 请求体校验，统一 422 错误格式 |
| 导入解析 | **openpyxl · python-docx · pdfplumber** | 分别解析 Excel / Word / PDF |
| RAG 解析 | **pypdfium2 · pdfminer.six** | 讲义 PDF 双引擎解析 + 可读性闸门 |
| RAG 检索 | **自实现 BM25(2-gram) + 余弦混合** | 不依赖分词词典和向量数据库 |
| 认知诊断 | **自实现 BKT** | 贝叶斯知识追踪，纯数学不依赖第三方库，可解释、可单测 |
| AI | **Ollama / 阿里云百炼** | 同一套 OpenAI 兼容接口，`LLM_PROVIDER` 切换；SSE 流式返回 |
| 前端 | **Vue 3 · TypeScript · Vite** | Composition API，`<script setup>` |
| 图表 / 公式 | **ECharts · KaTeX** | 学习报告图表、数学公式渲染 |
| 编排 | **Docker Compose · Nginx** | 四容器，Nginx 反代 + 静态托管 |

<details>
<summary><b>阿里云百炼这条路验证到哪一步了？</b></summary>

代码里是完整实现：`LLM_PROVIDER=bailian` 时走 DashScope 的 OpenAI 兼容端点，
切模型只改 `.env`。但**这条链路目前只跑通了单元测试，没有配真实 API Key 实测过**——
压测和日常开发全部用的本地 Ollama。买 Key 之前请按下面这步先自检：

```bash
cd backend && python scripts/check_llm.py
```

它会打印当前 provider、模型名，并发一次真实请求；连不上会明确说是网络、
Key 还是模型名的问题，而不是等到刷题时才报错。
</details>

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
│   │   ├── bkt.py              # 认知诊断模型（BKT），纯数学、不碰数据库
│   │   ├── mastery.py          # 掌握度落库 / 自适应选题打分 / 补齐
│   │   ├── llm.py              # 模型服务抽象：Ollama / 百炼 同一套接口
│   │   ├── rag/                # 讲义解析 / 切分 / 向量化 / 混合检索
│   │   ├── security.py         # JWT 密钥与算法（集中配置，生产环境缺密钥直接启动失败）
│   │   ├── agent/              # ReAct 循环 + Function Calling 工具
│   │   └── routes/             # auth / banks / import_questions / ai / rag / knowledge / mastery ...
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
| `CACHE_PREFIX` | `cuoti` | 缓存 key 前缀，多环境共用一台 Redis 时用来隔离 |
| `CACHE_TIMEOUT` | `0.1` | 单次 Redis 命令超时（秒），超时当作没缓存直接回源 |
| `CACHE_EXPLAIN_TTL` | `86400` | AI 解析缓存时长（秒） |
| `CACHE_QLIST_TTL` | `300` | 题目列表缓存时长（秒） |
| `CACHE_WAIT_TIMEOUT` | `120` | 没抢到重建锁时最多等多久（秒）。**必须大于单次模型生成耗时**，否则防击穿退化成各请求都回源 |
| `CACHE_LOCK_TTL` | `180` | 重建锁的 TTL（秒） |
| `IMPORT_CHUNK_SIZE` | `500` | 导入时每多少条一个事务 |
| `AI_API_BASE` | `http://localhost:11434` | Ollama 地址 |
| `AI_MODEL` | `qwen2.5:7b` | 模型名，必须和 `ollama list` 里的一致（实测用 `gemma3:4b`） |
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
ollama pull qwen2.5:7b        # 代码里的默认值

# 3. 确认服务在跑
curl http://localhost:11434/api/tags
```

然后改 `.env` 里的两行：

```env
AI_API_BASE=http://host.docker.internal:11434
AI_MODEL=qwen2.5:7b
```

改完重启后端：`docker compose restart backend`。

> **本项目实测用的是 `gemma3:4b`**（约 3.3GB，压测、自动打标、认知诊断全链路都是它跑的），
> `qwen2.5:7b` 只是代码默认值和通用推荐、本机没有实测。
> 换模型只改 `AI_MODEL`，但**效果会变**——小模型在自动打标时会照抄提示词里的示例，
> 代码里已经把示例的题号换成本批真实题号来兜住这个行为（见下方「知识点自动打标」）。

> 容器访问宿主机的 Ollama 走 `host.docker.internal`。
> 这个域名 Docker Desktop 自带；Linux 上本项目已经在 `docker-compose.yml`
> 里用 `extra_hosts: host-gateway` 映射好了，不用再改。

---

## 📊 性能

用 **2 万题**（20911 行）的题库压过一轮，单机、客户端和服务端在同一台机器上，
所以绝对值偏悲观，看**相对变化**才有意义。

### 真正解决问题的是分页，不是索引

| 场景 | 改造前 | 改造后 |
|---|---|---|
| 整包返回（`list_all`）P95 | 18.4s / 8.1MB | **20.3s / 8.1MB** |
| 分页取 20 条（`list_page20`）P95 | — | 949ms（冷）/ **66ms**（热）· 8.5KB |

**这里必须说清楚：整包接口并没有变快**（18.4s → 20.3s，同一个 8.1MB 响应体，
波动范围内）。改造后的价值和代价是分开的：

- 值的地方：前端原来一进题库页就拉 8MB，现在按页拉 8.5KB，**体积降到 1/956**。
  另一次同库实测：整包 2040ms / 8236.9KB，一页 50 条 12ms / 15.4KB（1/535）。
- 代价：**只要还有客户端去拉整包，它一样是 20 秒**。接口没有变快，
  只是前端不再那么用了。真要让整包也变快，得改成游标分页 + 强制 `limit` 上限。

为什么加索引救不了整包：整包是 **CPU 密集**的——单请求 1585ms，
10 并发 P95 掉到 16547ms（GIL 下序列化 2 万个 ORM 对象），
瓶颈不在索引，而在"把 2 万行变成 JSON"这件事本身。

### AI 解析缓存

| 场景 | 改造前 | 改造后 |
|---|---|---|
| 命中缓存 P95 | 118.0s | **33ms** |
| 冷启动单次（本地 gemma3:4b） | — | 约 25 ~ 28s |

改造前没有缓存，同一个问题问几遍就调几遍模型（一次 20 秒以上）。
现在缓存 key 里带**题目内容哈希 + 用户答案哈希 + 本次检索到的片段 id**，
题目内容一改 key 就变，不需要手动失效，也不会拿旧引用回答新知识库。

### 防击穿锁的边界（一个没做完美的点）

同题 5 并发，**默认配置**下锁生效了：1 次模型调用 / 25.2s，另外 4 个命中缓存。

但这个机制不是无条件的。等待方最多等 `CACHE_WAIT_TIMEOUT`（默认 120s），
超时就放弃并各自回源。把窗口压到 8s 复现一次：

| 等待窗口 | 模型调用次数 | 墙钟时间 |
|---|---|---|
| 120s（默认） | 1 次 | 25.2s |
| 8s | 5 次 | 144.4s |

也就是说：**首次生成必须在等待窗口内完成，锁才成立**。本地模型 5 并发抢 CPU 时
单次能拖到 200 秒以上，这时等待方全部超时，防击穿退化成"5 个请求各调一次模型"。
更稳的做法是等待方超时后**继续等**（而不是回源），或者把窗口按模型实测耗时配置；
现在的实现选择了"宁可直接回源也不让用户干等"。

### 导入容错

1000 题、其中 8% 是脏数据（缺选项、答案不在选项里、题型非法等 5 类）：

| 版本 | 结果 |
|---|---|
| 改造前 | **整包失败**，0 行入库，只报一条错 |
| 改造后 | 911 行入库 / 80 行失败 / 9 行去重，失败行**逐条附原因** |

### 复现

```bash
cd backend
python scripts/seed_data.py --questions 20000      # 造数据集
python scripts/bench_api.py --base-url http://127.0.0.1:3000 --bank-id 1

# 分页 / 服务端搜索 / 计数：这个脚本打的是 3002（bench 库），
# 地址用环境变量 BASE 覆盖
BASE=http://127.0.0.1:3002 python scripts/bench_questions_api.py
```

`bench_questions_api.py` 顶部注释里记着本机实测数字，改完代码可以直接对照重跑。

---

## 🧪 测试

```bash
cd backend
pip install -r requirements.txt
pytest -q
```

共 **325 个**后端测试，覆盖认证与账号安全、题库 CRUD、答题判分、越权访问、
批量导入、分页与缓存一致性、RAG 解析与混合检索、知识点打标、
以及认知诊断（BKT）与自适应选题（其中 BKT 44 条、诊断接口 32 条）。
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
<summary><b>掌握度全是 0.30、自适应选题说「没有可用知识点」</b></summary>

这是**正常现象**，不是 bug：诊断的对象是知识点，而知识点要先打标才有。

1. 进题库页 → 「知识点」区域 → 点自动打标（先 `dry_run` 看提示词也行）；
2. 或者进 `/knowledge` 页面批量打标。

题目一个知识点都没有时，自适应选题会退化成"按题号顺序出没做过的题"
（接口里明确返回 `strategy=fallback_no_kp`），不会假装在诊断。
另外跑批用的是本地模型，**1 批 10 题约 20 秒，2 万题全量约 12 小时**，
先用 `TAG_BATCH_SIZE` 或页面上的数量上限小范围试。
</details>

<details>
<summary><b>自动打标报「没有解析出有效知识点」</b></summary>

错误信息里会带上**模型实际返回的题号**，先看这个。最常见的原因是模型
（尤其是 4B 这种小模型）把提示词示例里的题号照抄了回来，导致每条都被
"题号不在本批"丢掉。代码里已经把示例题号换成本批真实题号，
如果你的老版本还会这样，先确认 `backend/app/knowledge.py` 是最新的。

另一个可能是整批输出不是 JSON（模型跑偏了），这时把模型换大一点，
或者把 `TAG_BATCH_SIZE` 调小。
</details>

<details>
<summary><b>老库升级后报缺表 / 查询很慢</b></summary>

`create_all` 只会**新建缺失的表**，不会给已存在的表补索引。
- 新功能需要的表（知识点、讲义、掌握度）启动时会自动建好；
- 但**索引不会自动补**。老库请手工执行缺的 `ALTER TABLE ... ADD INDEX`，
  否则掌握度/统计这类查询会走全表扫描。

另外 `create_all` 不会改已有列的类型：`selected_answer` 在旧库里可能是
`varchar(255)`，存长答案会被截断（模型里声明的是 `String(255)`，
本地库实际是 `varchar(500)`）。
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
