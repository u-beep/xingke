# 型刻 / ShapeAI

AI 身材管理应用：AI 对话 + 饮食/运动/饮水/体重记录 + 外卖选购 + 冰箱食材管理与菜谱推荐。

## 项目结构

```
├── xingke_frontend/   # 前端（React + TypeScript + Vite）
├── shapeai/           # 后端（FastAPI，AI 能力中台）
├── docker/            # 本地开发数据库服务栈（PG / Redis / MySQL / Milvus / MinIO）
├── Dockerfile         # 后端 API 镜像
└── docker-compose.prod.yml  # 生产部署编排（数据服务 + 后端 + 前端）
```

## 快速开始

### 1. 启动数据库

```bash
docker compose -f docker/docker-compose.yml up -d
```

首次启动后执行一次数据库迁移（建表）：

```bash
.venv/bin/python -m shapeai.migrate
```

### 2. 配置环境变量

```bash
cp .env.example .env   # 填入模型 API Key；SHAPEAI_PORT 默认用 28900
```

### 3. 启动后端（端口 28900）

```bash
.venv/bin/python -m shapeai serve            # 普通模式
.venv/bin/python -m shapeai serve --reload   # 开发热重载（改代码自动重启）
```

调试入口（PyCharm 断点调试）：`debug_server.py`；Swagger UI 见 http://localhost:28900/docs

### 4. 启动前端（端口 3000）

```bash
cd xingke_frontend
npm install
npm run dev
```

浏览器打开 http://localhost:3000 ，注册账号即可使用（数据库/Redis 未起时无法登录）。

## 功能页面

| 页面 | 说明 |
| --- | --- |
| AIChat | AI 对话；说到「吃了/喝了」会自动弹出饮食/饮水确认卡，确认后计入当日统计 |
| DietRecord | 饮食记录与热量统计 |
| ExercisePlan | 运动计划与打卡 |
| Activities | 锻炼活动（组局/群聊） |
| Fridge | 冰箱食材管理、拍照识别、菜谱推荐 |
| Takeout | 外卖选购 |
| Profile | 个人资料、体重记录 |

## 常用命令

```bash
# 健康检查
curl http://localhost:28900/health

# 活动模块测试数据（可选）
.venv/bin/python -m shapeai.seed_activities

# 前端生产构建
cd xingke_frontend && npm run build
```

## 管理界面（docker compose 启动后可用）

| 工具 | 地址 | 登录 |
| --- | --- | --- |
| pgAdmin (PostgreSQL) | http://localhost:8080 | admin@shapeai.com / shapeai123 |
| phpMyAdmin (MySQL) | http://localhost:8081 | root / 123456 |
| Redis Commander | http://localhost:8082 | admin / shapeai123 |
| Attu (Milvus) | http://localhost:8000 | — |
| MinIO Console | http://localhost:19001 | minioadmin / minioadmin |

## 生产部署

```bash
# 前置：项目根目录存在 .env（含模型 API Key）
docker compose -f docker-compose.prod.yml up -d --build
```

后端镜像启动时会自动循环执行数据库迁移，就绪后再拉起 API 服务。
