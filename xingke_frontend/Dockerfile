# 前端构建 + Nginx 托管
# 构建: docker build -t xingke-web .

# ─── 阶段1: Vite 构建静态文件 ───
FROM node:20-alpine AS builder

# 国内服务器默认走 npmmirror; 海外构建可用:
#   docker build --build-arg NPM_REGISTRY=https://registry.npmjs.org .
ARG NPM_REGISTRY=https://registry.npmmirror.com

WORKDIR /app
COPY package.json ./
RUN npm install --registry=${NPM_REGISTRY}
COPY . .
RUN npm run build

# ─── 阶段2: Nginx 静态托管 + API 反向代理 ───
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
