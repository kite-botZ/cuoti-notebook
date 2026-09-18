---
name: cuoti-notebook
description: 错题本/刷题宝项目的开发约定。涉及 FastAPI 后端、Vue3 前端、MySQL 数据模型、JWT 认证、题库/题目/答题/错题本相关改动时使用。
---

# 错题本项目

## 项目定位

一个前后端分离的刷题系统。用户可以创建题库、录入题目、答题判分、自动收集错题、收藏、写笔记、斩题。

## 目录结构

    backend/                      FastAPI 后端
      app/
        main.py                   入口：注册路由、建表
        db.py                     引擎、Session、Base、get_db
        models.py                 所有 SQLAlchemy 模型
        routes/
          auth.py                 注册/登录/验证码/重置密码
          banks.py                题库/题目/答题/状态/进度
      run.py                      启动脚本（uvicorn）
      requirements.txt

    frontend/                     Vue3 前端
      src/
        api/request.ts            axios 实例（baseURL=/api，自动带 token）
        router/index.ts           路由表 + 登录守卫
        utils/practiceState.ts    （待废弃，状态已迁到后端）
        views/
          Login.vue / Register.vue / Forgot.vue
          Home.vue                题库列表
          Bank.vue                题库详情
          Practice.vue            答题页

## 技术栈

后端：Python 3.10+、FastAPI、SQLAlchemy 2.x、PyMySQL、PyJWT、MySQL 8
前端：Vue3 + TypeScript、Vite、vue-router 4、axios

## 数据模型

- User(id, username 唯一, password 明文, created_at)
- QuestionBank(id, user_id, name, subject, description, created_at, updated_at)
- Question(id, bank_id, stem, question_type, options JSON, correct_answer int, explanation, is_archived, created_at, updated_at)
- AnswerAttempt(id, user_id, question_id, selected_answer, is_correct, answered_at) — 只增不改
- QuestionUserState(id, user_id, question_id, is_favorite, is_cut, note, wrong_count, updated_at) — 每个用户对每道题唯一

外键均 ondelete="CASCADE"。`QuestionUserState` 有 (user_id, question_id) 联合唯一约束。

## API 约定

- 统一前缀 `/api`
- 认证：请求头 `Authorization: Bearer <token>`，用 `HTTPBearer(auto_error=False)` 解析
- 未登录返回 401，detail 为「请先登录」；token 失效返回 401，detail 为「登录已失效，请重新登录」
- 资源不存在返回 404，detail 为具体名称，如「题库不存在」
- 校验失败返回 422
- 题目列表接口**不返回 correct_answer 和 explanation**，只有提交答案的接口才返回
- 所有依赖用户身份的接口都要先校验资源归属，防止越权

## 编码约定

后端：
- 所有跨文件导入写 `from app.xxx import yyy`
- 数据库字段 snake_case，Pydantic 模型字段也 snake_case
- 一个请求里多次写库，只在最后 commit 一次
- 注释用中文，说明「为什么」而不是「做了什么」
- 新接口放到 `routes/` 下对应文件，不要塞进 main.py

前端：
- 统一用 `@/api/request.ts` 的 request 实例，不要直接 import axios
- 路径别名 `@` 指向 `src`
- 页面放 `views/`，通用组件放 `components/`
- 组件用 `<script setup lang="ts">`
- 样式写在 `<style scoped>` 里，不引入全局 css 文件
- 注释用中文

## 常见任务套路

新增一个后端接口：
1. 在 `models.py` 确认或添加模型
2. 在 `routes/` 对应文件里加 Pydantic 请求体 + 路由函数
3. 需要登录就加 `user_id: int = Depends(current_user_id)`
4. 需要数据库就加 `db: Session = Depends(get_db)`
5. 在 `/docs` 里用 Authorize 填 token 测一遍

新增一个前端页面：
1. `views/` 下建 `.vue`
2. `router/index.ts` 里注册，需要登录的路径不要在 whiteList 里
3. 通过 `request` 调后端接口
4. 数据不要写 localStorage，全部走后端

## 禁止事项

- 不要把业务状态存 localStorage（token 和 username 除外）
- 不要硬编码 SECRET_KEY，生产要改成环境变量
- 不要返回 correct_answer 给未提交答案的请求
- 不要在接口里直接 db.commit() 多次
- 不要写 `from db import`（少了 app. 前缀）
- 不要给 `.vue`、`.ts` 文件顶上加 `// @ts-nocheck` 掩盖类型错误