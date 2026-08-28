"""用户记忆分层管理。

三层记忆架构：
- 短期记忆：单轮对话上下文（最近几条消息摘要）
- 中期记忆：近期健康状态（体重趋势、饮食打卡、运动记录摘要）
- 长期记忆：用户画像标签（身高、目标、偏好、忌口等）
"""

import re
from collections import deque


MAX_SHORT_TERM = 20       # 短期记忆最多保留 20 条
MAX_MID_TERM_ITEMS = 10   # 中期记忆每类最多 10 条


class LayeredMemory:
    """分层记忆管理器。

    管理用户的三层记忆，提供记忆检索和更新接口。
    短期记忆高频读写，缓存到 Redis 加速访问。
    中长期记忆持久化到 PostgreSQL user_memories 表。
    """

    def __init__(self, state: dict | None = None, user_id: str = "anonymous"):
        self.user_id = user_id
        self.state = state or {
            "short_term": [],
            "mid_term": {},
            "long_term": {},
        }
        self.short_term: deque = deque(self.state.get("short_term", []), maxlen=MAX_SHORT_TERM)
        self.mid_term: dict = self.state.get("mid_term", {})
        self.long_term: dict = self.state.get("long_term", {})

        self._db_mode = False
        try:
            from ..database import redis_client
            redis_client().ping()
            self._db_mode = True
        except Exception:
            pass

    def to_dict(self) -> dict:
        """序列化为字典。"""
        self.state["short_term"] = list(self.short_term)
        self.state["mid_term"] = self.mid_term
        self.state["long_term"] = self.long_term
        return self.state

    # ─── 短期记忆 ───

    def add_message(self, role: str, content: str, metadata: dict | None = None):
        """添加一条对话消息到短期记忆。"""
        self.short_term.append({
            "role": role,
            "content": content[:500],  # 截断防止膨胀
            "metadata": metadata or {},
        })
        # 写 Redis 缓存 (LRU list, TTL 1h)
        if self._db_mode:
            try:
                from ..database import redis_client
                import json
                r = redis_client()
                key = f"shapeai:memory:short:{self.user_id}"
                r.lpush(key, json.dumps({
                    "role": role, "content": content[:500], "metadata": metadata or {}
                }, ensure_ascii=False))
                r.ltrim(key, 0, MAX_SHORT_TERM - 1)  # 只保留最近 MAX_SHORT_TERM 条
                r.expire(key, 3600)
            except Exception:
                pass

    def get_recent(self, limit: int = 6) -> list[dict]:
        """获取最近的对话消息。"""
        return list(self.short_term)[-limit:]

    # ─── 中期记忆 ───

    def update_mid_term(self, category: str, item: dict):
        """更新中期记忆中的某个类别。

        Args:
            category: 类别（weight_records / diet_records / exercise_records）
            item: 记录项
        """
        bucket = self.mid_term.setdefault(category, [])
        bucket.append(item)
        # 保持每类不超过上限
        if len(bucket) > MAX_MID_TERM_ITEMS:
            self.mid_term[category] = bucket[-MAX_MID_TERM_ITEMS:]

    def get_mid_term(self, category: str) -> list[dict]:
        """获取中期记忆中某个类别的记录。"""
        return self.mid_term.get(category, [])

    # ─── 长期记忆 ───

    def set_user_profile(self, key: str, value):
        """设置用户画像标签。"""
        self.long_term[key] = value

    def get_user_profile(self, key: str, default=None):
        """获取用户画像标签。"""
        return self.long_term.get(key, default)

    def get_all_profile(self) -> dict:
        """获取完整用户画像。"""
        return dict(self.long_term)

    def update_profile(self, profile: dict):
        """批量更新用户画像。"""
        self.long_term.update(profile)
        # 写 Redis 缓存
        if self._db_mode:
            try:
                from ..database import redis_client
                import json
                r = redis_client()
                key = f"shapeai:memory:profile:{self.user_id}"
                r.set(key, json.dumps(self.long_term, ensure_ascii=False), ex=86400)
            except Exception:
                pass

    # ─── 检索 ───

    def retrieve_relevant(self, query: str, limit: int = 3) -> list[dict]:
        """从记忆中检索与查询相关的条目。

        MVP 版本：简单的关键词匹配。
        """
        # 分词：英文按词、中文按字，避免混合文本被当作一个 token
        query_tokens = set(re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", query.lower()))
        if not query_tokens:
            return []

        scored = []
        # 搜索短期记忆
        for item in self.short_term:
            text = str(item.get("content", "")).lower()
            item_tokens = set(re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text))
            overlap = len(query_tokens & item_tokens)
            if overlap > 0:
                scored.append((overlap, "short_term", item))

        # 搜索中期记忆
        for category, items in self.mid_term.items():
            for item in items:
                text = str(item).lower()
                item_tokens = set(re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text))
                overlap = len(query_tokens & item_tokens)
                if overlap > 0:
                    scored.append((overlap, f"mid_term:{category}", item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"source": src, "data": data} for _, src, data in scored[:limit]]

    # ─── 渲染 ───

    def render_memory_text(self) -> str:
        """渲染记忆为给模型看的紧凑文本。"""
        lines = ["Memory:"]
        # 用户画像
        profile = self.long_term
        if profile:
            lines.append(f"- user_profile: {profile}")
        else:
            lines.append("- user_profile: (empty)")
        # 最近对话
        recent = self.get_recent(3)
        if recent:
            lines.append(f"- recent_conversation: {len(recent)} messages")
            for msg in recent:
                lines.append(f"  [{msg['role']}] {msg['content'][:80]}...")
        else:
            lines.append("- recent_conversation: (empty)")
        # 中期记忆
        mid_summary = {k: len(v) for k, v in self.mid_term.items()}
        lines.append(f"- mid_term_summary: {mid_summary or '(empty)'}")
        return "\n".join(lines)
