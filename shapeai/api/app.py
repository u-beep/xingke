"""FastAPI 应用工厂。

创建并配置 FastAPI 应用，注册所有路由，
注入模型网关、工具执行器、知识库等依赖。
"""

import logging
from typing import Optional

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..gateway import ModelGateway, CostTracker
from ..agent import SessionStore
from ..agent.runtime import ShapeAgent
from ..tools import ToolExecutor, build_tool_registry
from ..rag import KnowledgeBase
from ..vision import FoodRecognitionService
from ..safety import SafetyGuard
from ..config import API_KEY, __version__, SYNC_ENABLED, SYNC_INTERVAL_SECONDS, CRAWLER_ENABLED, CRAWLER_INTERVAL_SECONDS
from ..sync_pg_to_mysql import SyncScheduler
from ..knowledge_fetcher import KnowledgeFetcher, FetchScheduler
from .security import auth_middleware
from .routes import (
    chat_router, tools_router, knowledge_router, image_router, profile_router,
    weight_router, diet_router, hydration_router, exercise_router, exercise_plan_router, workout_router, dashboard_router,
    goals_router, feedback_router, export_router, takeout_router, fridge_router,
    auth_router,
)

logger = logging.getLogger(__name__)


class AppState:
    """应用全局状态，持有所有共享组件。"""

    def __init__(self):
        self.gateway: Optional[ModelGateway] = None
        self.session_store: Optional[SessionStore] = None
        self.tool_executor: Optional[ToolExecutor] = None
        self.knowledge_base: Optional[KnowledgeBase] = None
        self.food_recognition: Optional[FoodRecognitionService] = None
        self.safety_guard: Optional[SafetyGuard] = None
        self.sync_scheduler: Optional[SyncScheduler] = None
        self.fetch_scheduler: Optional[FetchScheduler] = None
        self._agents: dict[str, ShapeAgent] = {}  # session_id -> agent 缓存

    def initialize(self, gateway: ModelGateway | None = None):
        """初始化所有组件。"""
        self.gateway = gateway or ModelGateway()
        self.session_store = SessionStore()
        self.tool_executor = ToolExecutor(self.gateway)
        self.knowledge_base = KnowledgeBase()
        self.knowledge_base.initialize()
        self.food_recognition = FoodRecognitionService(self.gateway)
        self.safety_guard = SafetyGuard()

        # 启动 PG -> MySQL 定时同步
        if SYNC_ENABLED:
            try:
                self.sync_scheduler = SyncScheduler(
                    interval_seconds=SYNC_INTERVAL_SECONDS,
                    full_sync_on_start=True,
                )
                self.sync_scheduler.start()
                logger.info("PG -> MySQL 定时同步已启动, 间隔=%ds", SYNC_INTERVAL_SECONDS)
            except Exception as exc:
                logger.warning("定时同步启动失败(不影响主服务): %s", exc)
        else:
            logger.info("PG -> MySQL 定时同步已禁用")

        # 启动知识拉取定时任务 (官方 API -> Milvus)
        if CRAWLER_ENABLED:
            try:
                fetcher = KnowledgeFetcher(knowledge_base=self.knowledge_base)
                self.fetch_scheduler = FetchScheduler(
                    fetcher=fetcher,
                    interval_seconds=CRAWLER_INTERVAL_SECONDS,
                )
                self.fetch_scheduler.start()
                logger.info("知识拉取定时任务已启动, 间隔=%ds", CRAWLER_INTERVAL_SECONDS)
            except Exception as exc:
                logger.warning("知识拉取启动失败(不影响主服务): %s", exc)
        else:
            logger.info("知识拉取定时任务已禁用")

        logger.info("ShapeAI 应用状态初始化完成")

    def create_agent(
        self,
        session_id: str | None = None,
        user_id: str = "anonymous",
        user_profile: dict | None = None,
    ) -> ShapeAgent:
        """创建或恢复 agent 实例。"""
        # 如果有session_id且缓存中有，直接返回
        if session_id and session_id in self._agents:
            return self._agents[session_id]

        # 构建工具注册表
        tools = build_tool_registry(self.tool_executor)

        if session_id:
            # 恢复已有会话
            try:
                agent = ShapeAgent.from_session(
                    gateway=self.gateway,
                    session_store=self.session_store,
                    session_id=session_id,
                    tools=tools,
                    tool_executor=self.tool_executor,
                    rag_retriever=self.knowledge_base,
                    safety_guard=self.safety_guard,
                    user_id=user_id,
                )
            except FileNotFoundError:
                # 会话不存在，新建
                agent = ShapeAgent(
                    gateway=self.gateway,
                    session_store=self.session_store,
                    user_id=user_id,
                    user_profile=user_profile,
                    tools=tools,
                    tool_executor=self.tool_executor,
                    rag_retriever=self.knowledge_base,
                    safety_guard=self.safety_guard,
                )
        else:
            # 新建会话
            agent = ShapeAgent(
                gateway=self.gateway,
                session_store=self.session_store,
                user_id=user_id,
                user_profile=user_profile,
                tools=tools,
                tool_executor=self.tool_executor,
                rag_retriever=self.knowledge_base,
                safety_guard=self.safety_guard,
            )

        # 缓存agent
        self._agents[agent.session["id"]] = agent
        return agent


# ─── API Key 鉴权中间件 ───
async def verify_api_key(request: Request):
    """验证API Key。"""
    # 健康检查端点不需要鉴权
    if request.url.path in ("/health", "/", "/docs", "/openapi.json", "/redoc"):
        return
    # 开发模式下不强制鉴权
    api_key = request.headers.get("X-API-Key", "")
    if API_KEY and api_key != API_KEY:
        # 允许无key访问（开发模式），生产环境应改为强制
        pass


def create_app(gateway: ModelGateway | None = None) -> FastAPI:
    """创建 FastAPI 应用实例。

    Args:
        gateway: 模型网关实例，None时自动构建
    Returns:
        配置好的 FastAPI 应用
    """
    app = FastAPI(
        title="ShapeAI 身材管理AI中台",
        description="""
独立部署的AI能力服务集群，收敛所有AI推理、生成、识别、分析类逻辑。

## 核心模块
1. **Agent调度与对话管理** — 对话全生命周期管理
2. **身材管理领域工具引擎** — BMR/TDEE/BMI计算、食谱生成、运动计划
3. **RAG知识检索** — 专业知识底座
4. **多模态图像识别** — 食物识别与营养计算
5. **大模型网关** — 多模型路由与降级
6. **安全与合规风控** — 医疗边界拦截、内容审核
        """,
        version=__version__,
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 初始化应用状态
    state = AppState()
    state.initialize(gateway)
    app.state = state

    # 注册路由
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(tools_router, prefix="/api/v1")
    app.include_router(knowledge_router, prefix="/api/v1")
    app.include_router(image_router, prefix="/api/v1")
    app.include_router(profile_router, prefix="/api/v1")
    app.include_router(weight_router, prefix="/api/v1")
    app.include_router(diet_router, prefix="/api/v1")
    app.include_router(hydration_router, prefix="/api/v1")
    app.include_router(exercise_router, prefix="/api/v1")
    app.include_router(exercise_plan_router, prefix="/api/v1")
    app.include_router(workout_router, prefix="/api/v1")
    app.include_router(dashboard_router, prefix="/api/v1")
    app.include_router(goals_router, prefix="/api/v1")
    app.include_router(feedback_router, prefix="/api/v1")
    app.include_router(export_router, prefix="/api/v1")
    app.include_router(takeout_router, prefix="/api/v1")
    app.include_router(fridge_router, prefix="/api/v1")

    # 全局登录鉴权中间件（解析 Bearer Token -> request.state.user_id，未登录访问受保护接口返回 401）
    app.middleware("http")(auth_middleware)

    # 健康检查
    @app.get("/health", tags=["系统"], summary="健康检查")
    async def health():
        return {
            "status": "ok",
            "version": __version__,
            "modules": {
                "gateway": state.gateway.health_check() if state.gateway else {},
                "knowledge_base": state.knowledge_base.get_stats() if state.knowledge_base else {},
                "safety": state.safety_guard.get_stats() if state.safety_guard else {},
                "sync": state.sync_scheduler.get_status() if state.sync_scheduler else {"running": False},
                "fetcher": state.fetch_scheduler.get_status() if state.fetch_scheduler else {"running": False},
            },
        }

    # 模型网关状态
    @app.get("/api/v1/gateway/stats", tags=["网关"], summary="模型网关状态")
    async def gateway_stats():
        return state.gateway.get_stats()

    # 安全统计
    @app.get("/api/v1/safety/stats", tags=["安全"], summary="安全拦截统计")
    async def safety_stats():
        return state.safety_guard.get_stats()

    # 安全拦截日志
    @app.get("/api/v1/safety/log", tags=["安全"], summary="安全拦截日志")
    async def safety_log(limit: int = 50):
        return {"records": state.safety_guard.get_interception_log(limit=limit)}

    # 根路径
    @app.get("/", tags=["系统"])
    async def root():
        return {
            "name": "ShapeAI 身材管理AI中台",
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
        }

    # 同步状态查询
    @app.get("/api/v1/sync/status", tags=["系统"], summary="PG->MySQL 同步状态")
    async def sync_status():
        if state.sync_scheduler:
            return state.sync_scheduler.get_status()
        return {"running": False, "enabled": SYNC_ENABLED}

    # 手动触发同步
    @app.post("/api/v1/sync/run", tags=["系统"], summary="手动触发 PG->MySQL 同步")
    async def sync_run(full: bool = False):
        from ..sync_pg_to_mysql import sync_all
        result = sync_all(full=full)
        return result

    # 知识拉取状态查询
    @app.get("/api/v1/knowledge/fetch/status", tags=["知识库"], summary="知识拉取状态")
    async def fetch_status():
        if state.fetch_scheduler:
            return state.fetch_scheduler.get_status()
        return {"running": False, "enabled": CRAWLER_ENABLED}

    # 手动触发知识拉取
    @app.post("/api/v1/knowledge/fetch/run", tags=["知识库"], summary="手动触发知识拉取")
    async def fetch_run():
        fetcher = KnowledgeFetcher(knowledge_base=state.knowledge_base)
        result = fetcher.fetch_all()
        return result

    # 应用关闭时停止调度器
    @app.on_event("shutdown")
    async def shutdown_schedulers():
        if state.sync_scheduler:
            state.sync_scheduler.stop()
            logger.info("PG -> MySQL 定时同步已停止")
        if state.fetch_scheduler:
            state.fetch_scheduler.stop()
            logger.info("知识拉取定时任务已停止")

    return app
