---
name: cuoti-notebook
description: 错题本/刷题宝项目的开发约定。涉及 FastAPI 后端、Vue3 前端、MySQL 数据模型、JWT 认证、题库/题目/答题/错题本、知识点打标与 RAG、认知诊断（BKT）与自适应选题相关改动时使用。
---

# 错题本项目

## 项目定位

一个前后端分离的刷题系统。用户可以创建题库、录入题目（含批量导入）、答题判分、
自动收集错题、收藏、写笔记、斩题；在题库上做知识点自动打标、讲义知识库（RAG）、
AI 讲解，并基于 BKT 掌握度做自适应选题。

## 目录结构

    backend/                      FastAPI 后端
      app/
        main.py                   入口：注册路由、建表
        db.py                     引擎、Session、Base、get_db
        models.py                 所有 SQLAlchemy 模型
        security.py               JWT 密钥与算法（生产缺密钥直接启动失败）
        cache.py                  Redis 缓存层：降级、版本号失效、SET NX 防击穿
        importer.py               四种格式（JSON/Excel/Word/PDF）逐行容错解析
        knowledge.py              知识点打标：提示词、解析、关联表写入
        bkt.py                    认知诊断模型（纯数学，不碰数据库）
        mastery.py                掌握度落库、自适应选题打分与补齐
        llm.py                    模型服务抽象：Ollama / 百炼同一套接口
        rag/                      讲义解析、切分、向量化、BM25+余弦混合检索
        agent/                    ReAct 循环 + Function Calling 工具
        routes/
          auth.py                 注册/登录/验证码/重置密码
          banks.py                题库/题目/答题/状态/进度/分页列表
          practice.py             练习会话
          stats.py                学习统计
          import_questions.py     批量导入
          upload.py               图片上传
          ai.py                   AI 解析（SSE 流式）+ AI 助手（ReAct）
          knowledge.py            知识点、讲义文档、打标接口
          rag.py                  检索调试接口
          mastery.py              掌握度总览 / 自适应选题 / 重置
          daily.py, user.py       每日一练、用户设置
      tests/                      13 个 test_*.py，344 条用例
      scripts/                    造数据、压测、冒烟、连通性自检、老库升级
      run.py                      启动脚本（uvicorn）
      requirements.txt

    frontend/                     Vue3 前端
      src/
        api/request.ts            axios 实例（baseURL=/api，自动带 token）
        router/index.ts           路由表 + 登录守卫
        composables/useToast.ts   全局提示
        utils/renderMarkdown.ts   Markdown + KaTeX 渲染
        utils/practiceState.ts    （待废弃，状态已迁到后端）
        components/               AiAssistant.vue / ToastContainer.vue
        views/
          Login.vue / Register.vue / Forgot.vue
          Home.vue                题库列表
          Bank.vue                题库详情（分页、打标、掌握度面板）
          Practice.vue            答题页（普通 / 错题 / 收藏 / 自适应；分页续拉）
          Stats.vue               学习统计
          Knowledge.vue           讲义知识库（上传、切分、检索调参、打标）

## 技术栈

后端：Python 3.12（兼容 3.11+）、FastAPI、SQLAlchemy 2.x、PyMySQL、PyJWT、
bcrypt、MySQL 8、Redis（5.x 起可用，显式走 RESP2）
前端：Vue3 + TypeScript、Vite、vue-router 4、axios、ECharts、KaTeX

## 数据模型

- User(id, username 唯一, password, created_at) — password 存 **bcrypt 哈希**；
  老数据里的明文密码在登录校验通过后自动升级成哈希
- QuestionBank(id, user_id, name, subject, description, created_at, updated_at)
- Question(id, bank_id, stem, question_type, options JSON, correct_answer, explanation, is_archived, created_at, updated_at)
- AnswerAttempt(id, user_id, question_id, selected_answer, is_correct, answered_at) — 只增不改
- QuestionUserState(id, user_id, question_id, is_favorite, is_cut, note, wrong_count, updated_at) — 每个用户对每道题唯一
- PracticeSession(id, user_id, bank_id, source, question_ids JSON, answers JSON, current_index, updated_at) —
  每个 (user_id, bank_id, source) 唯一，前端刷新/换设备都能接着答
- UserSettings(id, user_id 唯一, daily_goal, updated_at)
- KnowledgePoint(id, subject, name, parent_id, ...) + QuestionKnowledgePoint(question_id, kp_id, weight) —
  知识点与题目多对多。知识点是**全局共享**的（学科层面的公共分类，不挂 user_id），
  `(subject, name)` 唯一；`parent_id` 支持「函数 → 二次函数 → 顶点式」的层级
- UserKpMastery(id, user_id, kp_id, p_known, attempts, correct, last_answered_at, updated_at) —
  **唯一约束 (user_id, kp_id)**；索引 (user_id, p_known) 支撑"找最弱知识点"。
  user_id / kp_id 不再单独建索引：唯一约束的最左前缀已覆盖
- KnowledgeDocument(...) + DocumentChunk(...) — 讲义与切分片段（向量以 JSON 存 MySQL）

外键均 ondelete="CASCADE"。`QuestionUserState` 有 (user_id, question_id) 联合唯一约束。

## API 约定

- 统一前缀 `/api`
- 认证：请求头 `Authorization: Bearer <token>`，用 `HTTPBearer(auto_error=False)` 解析
- 未登录返回 401，detail 为「请先登录」；token 失效返回 401，detail 为「登录已失效，请重新登录」
- 资源不存在返回 404，detail 为具体名称，如「题库不存在」
- 校验失败返回 422
- 题目列表接口**不返回 correct_answer 和 explanation**，只有提交答案的接口才返回
- **列表接口一律分页**：`page` / `page_size` 参数，响应头带 `X-Total-Count` / `X-Has-More`。
  不要新增"一次返回整库"的列表接口——2 万题时整包是 8MB / 20 秒，
  前端只能拿到一个卡死的页面
- **分页之后，客户端手里的数据只有一页**：搜索、按状态/题型过滤、打乱顺序
  都必须由服务端做（`q` / `filter_type` / `question_type` / `has_image` / `ids`），
  否则只会筛出"当前页里符合条件的那些"，看起来像生效了其实没有。
  要在整个范围内随机，用 `/banks/{id}/question-ids` 取 id 后再分批取正文
- `/question-ids` 的过滤口径必须和 `/banks/{id}/questions` 完全一致
  （两边用同一套谓词），否则"打乱题序"会把不该出现的题排进来
- 所有依赖用户身份的接口都要先校验资源归属，防止越权

## 编码约定

后端：
- 所有跨文件导入写 `from app.xxx import yyy`
- 数据库字段 snake_case，Pydantic 模型字段也 snake_case
- 一个请求里多次写库，只在最后 commit 一次
- **例外：长跑批任务按批提交**。自动打标一次要调几十次模型、跑十几分钟，
  只在最后提交一次的话中途任何一次失败就全丢；改成每批 commit，
  失败时已完成的部分保留（`knowledge.py::tag_questions`）
- 注释用中文，说明「为什么」而不是「做了什么」
- 新接口放到 `routes/` 下对应文件，不要塞进 main.py

前端：
- 统一用 `@/api/request.ts` 的 request 实例，不要直接 import axios
- 路径别名 `@` 指向 `src`
- 页面放 `views/`，通用组件放 `components/`
- 组件用 `<script setup lang="ts">`
- 样式写在 `<style scoped>` 里，不引入全局 css 文件
- 注释用中文

## 认知诊断 / 自适应选题的约定

- **模型和存储分开**：`bkt.py` 只做数学（不 import 数据库），`mastery.py` 只做落库与选题。
  这样 BKT 能被 44 条测试单独钉住，不会被数据库细节污染
- 四个参数 `p_init=0.30 / p_learn=0.15 / p_slip=0.10 / p_guess=0.25`，
  必须满足 `1 - p_slip > p_guess`，否则模型不可辨识（`validate()` 会拒绝）
- 显示档位（熟练 0.90 / 基本掌握 0.72 / 薄弱 0.45）是**按模型真实轨迹反推**的，
  不是随手分的。改参数就要重新标定这几个阈值，并同步改 `test_bkt.py`
- 三个反直觉行为是**有意的**，不要"修"：连错会稳定在 0.173 而不是 0；
  连对会饱和在 0.99 而不是 1；单个 `p_guess` 区分不了"真会"和"蒙对"
- 用 `available_questions_query()` 取可用题目时，`user_id` 必须写在 JOIN 的
  **ON 子句**里，写到 WHERE 会让 LEFT JOIN 退化成 INNER JOIN，
  把"还没做过的题"全部筛掉
- 选题打分 = `explore + 0.5 * exploit`；目标知识点数是
  `min(MAX_TARGET_KPS, limit, 可用数)`，不要写成按 limit 折算（会让后面的知识点饿死）

## 测试约定

- 用 SQLite 内存库，不碰真实 MySQL；`conftest.py` 固定 `APP_ENV=testing`、
  `LLM_PROVIDER=ollama`、`JWT_SECRET_KEY`，测试里**不允许真的调模型或联网**
- 缓存在每个用例前清空（autouse fixture），避免用例之间互相污染
- 改 BKT / 选题逻辑时必须同时改 `test_bkt.py` / `test_mastery_api.py`：
  这两个文件里的断言是照真实数值写的，改了模型就会红，**先确认是模型错了还是断言错了**，
  不要直接把断言改松

## 数据库变更约定

- 新表直接加模型，应用启动时 `create_all` 会建（含索引）
- **给已有表加索引，`create_all` 不会补**。加完模型里的 `Index(...)` 之后，
  老库要跑 `python scripts/upgrade_db.py --apply`（幂等，已存在的会跳过）；
  这个脚本连的是 `.env` 里配的库，**对生产库先不带 `--apply` 预览**
- 改已有列的类型/名字 `create_all` 也不会做，要手工 `ALTER`，
  并且要想清楚老数据怎么办（比如 `selected_answer` 长度）

## 常见任务套路

新增一个后端接口：
1. 在 `models.py` 确认或添加模型
2. 在 `routes/` 对应文件里加 Pydantic 请求体 + 路由函数
3. 需要登录就加 `user_id: int = Depends(current_user_id)`
4. 需要数据库就加 `db: Session = Depends(get_db)`
5. 在 `/docs` 里用 Authorize 填 token 测一遍
6. 补一条 pytest 用例

新增一个前端页面：
1. `views/` 下建 `.vue`
2. `router/index.ts` 里注册，需要登录的路径不要在 whiteList 里
3. 通过 `request` 调后端接口
4. 数据不要写 localStorage，全部走后端

## 禁止事项

- 不要把业务状态存 localStorage（token 和 username 除外）
- 不要硬编码 SECRET_KEY，生产要改成环境变量
- 不要把 API Key 写进代码或提交到仓库，只放 `.env`（已 gitignore）
- 不要返回 correct_answer 给未提交答案的请求
- 不要在接口里直接 db.commit() 多次（长跑批任务按批提交是**有意的例外**）
- 不要写 `from db import`（少了 app. 前缀）
- 不要给 `.vue`、`.ts` 文件顶上加 `// @ts-nocheck` 掩盖类型错误
- 不要把整库列表返回给前端（见 API 约定里的分页要求）
- 不要在分页之后还在客户端做搜索 / 过滤 / 洗牌（作用范围只有当前页）
