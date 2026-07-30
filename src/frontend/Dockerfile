# 前端镜像：构建静态产物后交由 nginx 托管（system-architecture.md 第六节）。
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src

# 默认留空：nginx 已把 /api 同源代理到 api 容器，前端走相对路径即可，
# 无需跨域。若要让前端直连别处的后端，构建时传入完整地址。
ARG VITE_API_BASE=
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
