# 型刻 / ShapeAI

AI 身材管理应用：AI 对话 + 饮食/运动/饮水/体重记录 + 外卖选购 + 冰箱食材管理与菜谱推荐。

## 项目结构

```
├── xingke/    # 前端（React + TypeScript + Vite）
├── shapeai/   # 后端（FastAPI，AI 能力中台）
├── docker/    # 数据库服务栈（PostgreSQL / Redis / MySQL / Milvus / MinIO）
└── .venv/     # Python 虚拟环境
```

## 快速开始

### 1. 启动数据库

```bash
docker compose -f docker/docker-compose.yml up -d
```

### 2. 配置环境变量

```bash
cp .env.example .env   # 填入模型 API Key 等
```

### 3. 启动后端（端口 8900）

```bash
uv run shapeai          # 或: python -m shapeai
```

调试入口（PyCharm 断点调试）：`debug_server.py`，Swagger UI 见 http://localhost:8900/docs

### 4. 启动前端

```bash
cd xingke
npm install
npm run dev
```
