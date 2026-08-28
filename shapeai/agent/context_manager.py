"""Prompt 组装与上下文预算控制。

负责决定每一轮把多少 prefix、memory、历史、知识检索结果
以及当前用户请求送进模型。总预算默认 12000 字符，
超出时按优先级压缩各 section。
"""

from __future__ import annotations

DEFAULT_TOTAL_BUDGET = 12000
DEFAULT_SECTION_BUDGETS = {
    "prefix": 2000,        # 系统人设 + 工具规则
    "profile": 800,        # 用户个人资料（身高/体重/偏好等）
    "memory": 1500,        # 用户记忆
    "knowledge": 2000,     # RAG 检索结果
    "history": 4000,       # 对话历史
}
# 超预算时的压缩优先级：先牺牲知识检索，再牺牲历史，再牺牲个人资料
DEFAULT_REDUCTION_ORDER = ("knowledge", "history", "profile", "memory", "prefix")
SECTION_ORDER = ("prefix", "profile", "memory", "knowledge", "history", "current_request")
CURRENT_REQUEST_SECTION = "current_request"


def _tail_clip(text: str, limit: int) -> str:
    """从尾部截断文本，超长时加省略号。"""
    text = str(text)
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[:limit - 3] + "..."


class ContextManager:
    """上下文预算管理器。

    把系统人设 + 用户记忆 + RAG知识 + 对话历史 + 当前请求
    拼成完整 prompt，同时控制总字符数在预算内。
    """

    def __init__(self, agent, total_budget: int = DEFAULT_TOTAL_BUDGET):
        self.agent = agent
        self.total_budget = total_budget
        self.section_budgets = dict(DEFAULT_SECTION_BUDGETS)
        self.reduction_order = DEFAULT_REDUCTION_ORDER

    def build(self, user_message: str, knowledge_context: str = "", profile_context: str = "") -> tuple[str, dict]:
        """按预算组装一轮完整 prompt。

        Args:
            user_message: 用户当前请求
            knowledge_context: RAG 检索到的知识上下文
            profile_context: 用户个人资料上下文
        Returns:
            (prompt, metadata) 元组
        """
        section_texts = {
            "prefix": self.agent.prefix,
            "profile": profile_context or "User Profile:\n- none",
            "memory": self.agent.memory.render_memory_text(),
            "knowledge": knowledge_context or "Knowledge:\n- none",
            "history": self._render_history(),
            CURRENT_REQUEST_SECTION: f"Current user request:\n{user_message}",
        }

        budgets = dict(self.section_budgets)
        rendered = self._render_sections(section_texts, budgets)
        prompt = self._assemble(rendered)

        # 超预算时按优先级压缩
        reduction_log = []
        while len(prompt) > self.total_budget:
            overflow = len(prompt) - self.total_budget
            reduced = False
            for section in self.reduction_order:
                floor = max(100, self.section_budgets.get(section, 0) // 4)
                current = budgets.get(section, 0)
                if current <= floor:
                    continue
                new_budget = max(floor, current - overflow)
                if new_budget >= current:
                    continue
                reduction_log.append({
                    "section": section,
                    "before": current,
                    "after": new_budget,
                })
                budgets[section] = new_budget
                rendered = self._render_sections(section_texts, budgets)
                prompt = self._assemble(rendered)
                reduced = True
                break
            if not reduced:
                break

        metadata = {
            "prompt_chars": len(prompt),
            "prompt_budget": self.total_budget,
            "over_budget": len(prompt) > self.total_budget,
            "section_budgets": budgets,
            "reduction_log": reduction_log,
        }
        return prompt, metadata

    def _render_sections(self, texts: dict, budgets: dict) -> dict:
        """按预算渲染各 section。"""
        rendered = {}
        for section in SECTION_ORDER:
            if section == CURRENT_REQUEST_SECTION:
                raw = texts[section]
                rendered[section] = raw
            else:
                raw = texts.get(section, "")
                budget = budgets.get(section, 0)
                rendered[section] = _tail_clip(raw, budget) if budget > 0 else raw
        return rendered

    def _render_history(self) -> str:
        """渲染对话历史。"""
        history = self.agent.session.get("history", [])
        if not history:
            return "Transcript:\n- empty"
        lines = ["Transcript:"]
        recent = history[-10:]  # 最近 10 条
        for item in recent:
            role = item.get("role", "unknown")
            content = str(item.get("content", ""))[:200]
            if role == "tool":
                name = item.get("name", "unknown")
                lines.append(f"[tool:{name}] {content}")
            else:
                lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    def _assemble(self, rendered: dict) -> str:
        """组装最终 prompt。"""
        return "\n\n".join([
            rendered["prefix"],
            rendered["profile"],
            rendered["memory"],
            rendered["knowledge"],
            rendered["history"],
            rendered[CURRENT_REQUEST_SECTION],
        ]).strip()
