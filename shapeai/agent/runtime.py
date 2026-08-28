"""Agent 运行时核心 — ShapeAgent。

这是整个AI中台的调度中枢：模型网关、工具注册、记忆管理、
安全护栏、RAG检索都挂在这个对象上。
外部代码只需要调用 ask() 即可完成一次完整的 agent 运行。
"""

import json
import logging
from typing import Optional

from .session_store import SessionStore, create_session
from .memory import LayeredMemory
from .context_manager import ContextManager
from .prompt_center import PromptCenter
from .agent_loop import AgentLoop
from ..gateway import ModelGateway
from ..user_profile import ProfileStore, PreferenceUpdater
from ..records import DietExtractor, HydrationExtractor
from ..config import AGENT_MAX_STEPS, MODEL_MAX_TOKENS, CONTEXT_BUDGET

logger = logging.getLogger(__name__)


class ShapeAgent:
    """Agent 运行时门面类。

    整合模型网关、工具引擎、记忆管理、安全护栏、RAG检索，
    提供统一的 ask() 入口。
    """

    def __init__(
        self,
        gateway: ModelGateway,
        session_store: SessionStore,
        session: Optional[dict] = None,
        user_id: str = "anonymous",
        user_profile: Optional[dict] = None,
        tools: Optional[dict] = None,
        tool_executor=None,
        rag_retriever=None,
        safety_guard=None,
        max_steps: int = AGENT_MAX_STEPS,
        max_new_tokens: int = MODEL_MAX_TOKENS,
        context_budget: int = CONTEXT_BUDGET,
    ):
        """初始化 Agent 运行时。

        Args:
            gateway: 模型网关
            session_store: 会话存储
            session: 已有会话，None 时新建
            user_id: 用户ID
            user_profile: 用户画像（身高、体重、目标等）
            tools: 工具注册表
            tool_executor: 工具执行器
            rag_retriever: RAG 检索器
            safety_guard: 安全护栏
            max_steps: 最大工具调用步数
            max_new_tokens: 模型最大输出 token
            context_budget: 上下文预算
        """
        self.gateway = gateway
        self.session_store = session_store
        self.session = session or create_session(user_id, user_profile)
        self.user_id = user_id
        self.tools = tools or {}
        self.tool_executor = tool_executor
        self.rag_retriever = rag_retriever
        self.safety_guard = safety_guard
        self.max_steps = max_steps
        self.max_new_tokens = max_new_tokens

        # 初始化子组件
        self.memory = LayeredMemory(self.session.get("memory", {}))
        if user_profile:
            self.memory.update_profile(user_profile)

        # 用户个人资料管理
        self.profile_store = ProfileStore()
        self.preference_updater = PreferenceUpdater(gateway=gateway) if gateway else None

        # 饮食自动提取器
        self.diet_extractor = DietExtractor(gateway=gateway)

        # 饮水自动提取器
        self.hydration_extractor = HydrationExtractor(gateway=gateway)

        self.prompt_center = PromptCenter()
        self.prefix = self.prompt_center.build_prefix(self.tools)
        self.context_manager = ContextManager(self, total_budget=context_budget)

        # 持久化初始会话
        self.session_path = self.session_store.save(self.session)

    @classmethod
    def from_session(cls, gateway, session_store, session_id, **kwargs):
        """从已有会话 ID 恢复 agent 实例。"""
        session = session_store.load(session_id)
        return cls(gateway=gateway, session_store=session_store, session=session, **kwargs)

    def record(self, item: dict):
        """向会话历史追加一条记录并持久化。"""
        self.session["history"].append(item)
        self.session["memory"] = self.memory.to_dict()
        self.session_path = self.session_store.save(self.session)

    def execute_tool(self, name: str, args: dict) -> dict:
        """执行工具调用。

        如果配置了工具执行器，委托给执行器；
        否则直接查找并调用工具函数。
        """
        if self.tool_executor:
            return self.tool_executor.execute(name, args)

        tool = self.tools.get(name)
        if tool is None:
            return {"content": f"error: 未知工具 '{name}'"}

        run = tool.get("run")
        if run is None:
            return {"content": f"error: 工具 '{name}' 没有执行函数"}

        try:
            result = run(args)
            return {"content": str(result)}
        except Exception as exc:
            return {"content": f"error: 工具 '{name}' 执行失败: {exc}"}

    def retrieve_knowledge(self, query: str) -> str:
        """通过 RAG 检索相关知识。"""
        if not self.rag_retriever:
            return ""
        try:
            results = self.rag_retriever.retrieve(query, top_k=3)
            if not results:
                logger.info("RAG检索: 查询 '%s' 未命中任何知识", query)
                return ""
            logger.info("RAG检索成功: 查询 '%s' 命中 %d 条知识", query, len(results))
            for i, r in enumerate(results, 1):
                logger.info("  [%d] source=%s score=%.4f title=%s",
                            i, r.get('source', ''), r.get('score', 0),
                            r.get('title', '')[:50])
            lines = ["Knowledge (from RAG):"]
            for r in results:
                lines.append(f"- [{r.get('source', '')}] {r.get('content', '')[:300]}")
            return "\n".join(lines)
        except Exception as exc:
            logger.warning("RAG检索失败: %s", exc)
            return ""

    def ask(self, user_message: str) -> str:
        """执行一次完整的 agent 运行。

        Args:
            user_message: 用户请求文本
        Returns:
            模型的最终答案文本
        """
        # 输入安全检查
        if self.safety_guard:
            is_safe, reason, modified = self.safety_guard.guard_input(user_message)
            if not is_safe:
                response = f"抱歉，您的请求包含不安全内容: {reason}"
                self.record({"role": "user", "content": user_message})
                self.record({"role": "assistant", "content": response})
                return response
            user_message = modified or user_message

        loop = AgentLoop(self)
        return loop.run(user_message)

    def _ask_continuing(self, user_message: str) -> str:
        """继续执行 agent 循环（用户消息已通过 /send 入库，不重复写入）。

        与 ask() 的区别：跳过 AgentLoop 中重复记录用户消息的步骤。
        用于前端先调用 /send 入库，再调用 /stream 的场景。
        """
        loop = AgentLoop(self)
        loop._user_message_already_recorded = True
        return loop.run(user_message)

    def get_history(self, limit: int = 20) -> list[dict]:
        """获取对话历史。"""
        return self.session.get("history", [])[-limit:]

    def reset(self):
        """重置会话。"""
        self.session["history"] = []
        self.session["memory"] = {
            "short_term": [],
            "mid_term": {},
            "long_term": self.session.get("user_profile", {}),
        }
        self.memory = LayeredMemory(self.session["memory"])
        self.session_store.save(self.session)

    def update_profile(self, profile: dict):
        """更新用户画像。"""
        self.memory.update_profile(profile)
        self.session.setdefault("user_profile", {}).update(profile)
        self.session_store.save(self.session)
