"""Agent 控制循环。

实现 agent 的核心控制循环：
1. 感知：重新组装 prompt
2. 决策：让模型返回工具调用或最终答案
3. 行动：如果是工具调用，执行工具
4. 记录：把结果写回历史/记忆
然后进入下一轮，直到停机条件满足。
"""

import json
import re
import time
import logging

from ..user_profile import PreferenceUpdater

logger = logging.getLogger(__name__)

MAX_RETRIES = 3  # 模型输出格式错误的最大重试次数


class AgentLoop:
    """Agent 主循环控制器。

    驱动"感知→决策→行动→记录"循环，
    直到模型返回最终答案或达到步数/重试上限。
    """

    def __init__(self, agent):
        self.agent = agent
        # 标记用户消息是否已入库（通过 /send 接口）
        self._user_message_already_recorded = False

    def run(self, user_message: str) -> str:
        """执行一次完整的 agent 运行循环。

        Args:
            user_message: 用户请求文本
        Returns:
            模型的最终答案文本
        """
        agent = self.agent
        run_started_at = time.monotonic()

        # ─── 检查并更新用户个人资料 ───
        profile_context = ""
        if hasattr(agent, 'preference_updater') and agent.preference_updater:
            update_msg = agent.preference_updater.check_and_update(agent.user_id, user_message)
            if update_msg:
                logger.info("用户资料更新: %s", update_msg)

        # 加载用户个人资料上下文
        if hasattr(agent, 'profile_store') and agent.profile_store:
            profile = agent.profile_store.get(agent.user_id)
            profile_context = profile.to_context_text()
            logger.debug("已加载用户 %s 的个人资料", agent.user_id)

        # 记录用户消息（如果已通过 /send 入库则跳过）
        if not self._user_message_already_recorded:
            agent.record({"role": "user", "content": user_message})
        agent.memory.add_message("user", user_message)

        tool_steps = 0
        retries = 0
        max_steps = agent.max_steps

        # RAG 检索只执行一次（用户消息不变，结果也不变）
        knowledge_context = ""
        if agent.rag_retriever:
            knowledge_context = agent.retrieve_knowledge(user_message)

        while tool_steps < max_steps and retries < MAX_RETRIES:
            # ─── 感知：组装 prompt ───

            prompt, prompt_meta = agent.context_manager.build(user_message, knowledge_context, profile_context)
            logger.debug("Prompt built: %d chars, over_budget=%s",
                         prompt_meta["prompt_chars"], prompt_meta["over_budget"])

            # ─── 决策：调用模型 ───
            try:
                raw = agent.gateway.complete(
                    prompt,
                    max_new_tokens=agent.max_new_tokens,
                    user_id=agent.session.get("user_id", "anonymous"),
                    scene="chat",
                )
            except Exception as exc:
                logger.error("模型调用失败: %s", exc)
                final = f"抱歉，AI服务暂时不可用，请稍后再试。错误: {exc}"
                agent.record({"role": "assistant", "content": final})
                agent.memory.add_message("assistant", final)
                return final

            # ─── 解析模型输出 ───
            kind, payload = self._parse(raw)

            if kind == "retry":
                retries += 1
                agent.record({"role": "assistant", "content": payload, "retry": True})
                continue

            if kind == "tool":
                tool_steps += 1
                name = payload.get("name", "")
                args = payload.get("args", {})
                logger.info("执行工具: %s, args=%s", name, args)

                # 执行工具
                tool_result = agent.execute_tool(name, args)
                result_text = tool_result["content"]

                # 记录工具调用
                agent.record({
                    "role": "tool",
                    "name": name,
                    "args": args,
                    "content": result_text,
                })
                agent.memory.add_message("tool", f"[{name}] {result_text[:200]}")
                continue

            # ─── 最终答案 ───
            final = payload.strip() if payload else raw.strip()

            # 安全检查
            if agent.safety_guard:
                final = agent.safety_guard.guard_output(final)

            agent.record({"role": "assistant", "content": final})
            agent.memory.add_message("assistant", final)

            # ─── 饮食提取（不自动写入，交由前端确认）───
            diet_data = None
            if hasattr(agent, 'diet_extractor') and agent.diet_extractor:
                try:
                    diet_data = agent.diet_extractor.extract_only(
                        user_id=agent.user_id,
                        user_message=user_message,
                        ai_response=final,
                    )
                except Exception as exc:
                    logger.warning("饮食提取失败: %s", exc)

            # 如果提取到食物数据，追加 JSON 标记供前端解析
            if diet_data and diet_data.get("foods"):
                import json as _json
                marker = _json.dumps(diet_data, ensure_ascii=False)
                final = final + f"\n\n[DIET_DATA]{marker}[/DIET_DATA]"
                # 更新最后一条记录
                if agent.session.get("history"):
                    agent.session["history"][-1]["content"] = final
                    agent.session_store.save(agent.session)

            # ─── 饮水提取（不自动写入，交由前端确认）───
            water_data = None
            if hasattr(agent, 'hydration_extractor') and agent.hydration_extractor:
                try:
                    water_data = agent.hydration_extractor.extract_only(
                        user_id=agent.user_id,
                        user_message=user_message,
                        ai_response=final,
                    )
                except Exception as exc:
                    logger.warning("饮水提取失败: %s", exc)

            # 如果提取到饮水量数据，追加 JSON 标记供前端解析
            if water_data and water_data.get("amount_ml"):
                import json as _json
                marker = _json.dumps(water_data, ensure_ascii=False)
                final = final + f"\n\n[WATER_DATA]{marker}[/WATER_DATA]"
                # 更新最后一条记录
                if agent.session.get("history"):
                    agent.session["history"][-1]["content"] = final
                    agent.session_store.save(agent.session)

            duration_ms = int((time.monotonic() - run_started_at) * 1000)
            logger.info("Agent运行完成 tool_steps=%d retries=%d duration=%dms diet_extracted=%s water_extracted=%s",
                        tool_steps, retries, duration_ms, diet_data is not None, water_data is not None)
            return final

        # 循环结束但未得到最终答案
        if retries >= MAX_RETRIES:
            final = "抱歉，我无法理解您的请求，请换一种方式描述。"
        else:
            final = "抱歉，我已达到处理步数上限，请简化您的请求或分步提问。"

        agent.record({"role": "assistant", "content": final})
        agent.memory.add_message("assistant", final)
        return final

    @staticmethod
    def _parse(raw: str) -> tuple[str, str | dict]:
        """解析模型输出为结构化动作。

        Returns:
            (kind, payload) — kind 可能是 "tool" / "final" / "retry"
        """
        raw = str(raw).strip()

        # 工具调用：<tool>...</tool>
        if "<tool>" in raw:
            start = raw.find("<tool>") + len("<tool>")
            end = raw.find("</tool>", start)
            if end == -1:
                return "retry", "工具调用格式错误：缺少 </tool> 闭合标签"
            body = raw[start:end].strip()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return "retry", "工具调用JSON解析失败"
            if not isinstance(payload, dict):
                return "retry", "工具调用必须是JSON对象"
            if not str(payload.get("name", "")).strip():
                return "retry", "工具调用缺少name字段"
            payload.setdefault("args", {})
            return "tool", payload

        # 最终答案：<final>...</final>
        if "<final>" in raw:
            start = raw.find("<final>") + len("<final>")
            end = raw.find("</final>", start)
            if end == -1:
                final = raw[start:].strip()
            else:
                final = raw[start:end].strip()
            if final:
                return "final", final
            return "retry", "最终答案为空"

        # 没有标签但有内容，当作最终答案
        if raw:
            return "final", raw

        return "retry", "模型返回空响应"
