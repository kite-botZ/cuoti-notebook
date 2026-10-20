# ==================== 阶段 1：构建 ====================
# 版本要跟 package.json 的 engines 字段对齐（^22.18.0 || >=24.12.0）：
# 原来用 node:20 构建，不满足引擎要求，vite 8 在 20 上会装/构建失败。
FROM node:22-alpine AS builder

WORKDIR /app

# 先装依赖（利用缓存）
COPY package*.json ./
RUN npm ci

# 复制源码并构建
COPY . .
RUN npm run build

# ==================== 阶段 2：运行 ====================
FROM nginx:1.27-alpine

# 删掉默认配置
RUN rm /etc/nginx/conf.d/default.conf

# 复制我们的 Nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 从构建阶段复制产物
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]