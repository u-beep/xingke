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
import threading

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

            duration_ms = int((time.monotonic() - run_started_at) * 1000)
            logger.info("Agent运行完成 tool_steps=%d retries=%d duration=%dms",
                        tool_steps, retries, duration_ms)

            # ─── 异步提取：不阻塞主回复返回 ───
            # 饮食/饮水提取不再同步等待（原先串行 2 次 LLM 往返拖慢首字返回），
            # 改为提交到后台线程池，结果通过 agent.last_extract_result 暴露，
            # 由 /chat/poll 或 /chat/extract 接口拉取。
            self._submit_extraction(user_message, final)

            return final

        # 循环结束但未得到最终答案
        if retries >= MAX_RETRIES:
            final = "抱歉，我无法理解您的请求，请换一种方式描述。"
        else:
            final = "抱歉，我已达到处理步数上限，请简化您的请求或分步提问。"

        agent.record({"role": "assistant", "content": final})
        agent.memory.add_message("assistant", final)
        return final

    # ─────────────────────────────────────────────────────────────
    #  异步提取（后台线程）
    # ─────────────────────────────────────────────────────────────

    def _submit_extraction(self, user_message: str, ai_response: str) -> None:
        """把饮食/饮水提取提交到后台线程，不阻塞主回复返回。

        优先使用 CombinedExtractor（一次 LLM 调用同时提取两类记录），
        完成后把结果写入 agent.last_extract_result 供接口层拉取。
        """
        agent = self.agent
        extractor = getattr(agent, "combined_extractor", None)
        if extractor is None:
            # 未配置合并提取器时回退：分别用两个提取器（仍异步，不阻塞返回）
            diet_ex = getattr(agent, "diet_extractor", None)
            water_ex = getattr(agent, "hydration_extractor", None)
            if not diet_ex and not water_ex:
                return

            def _legacy_extract():
                diet_data = None
                water_data = None
                try:
                    if diet_ex:
                        d = diet_ex.extract_only(user_id=agent.user_id, user_message=user_message, ai_response=ai_response)
                        if d and d.get("foods"):
                            diet_data = d
                except Exception as exc:
                    logger.warning("饮食提取失败: %s", exc)
                try:
                    if water_ex:
                        w = water_ex.extract_only(user_id=agent.user_id, user_message=user_message, ai_response=ai_response)
                        if w and w.get("amount_ml"):
                            water_data = w
                except Exception as exc:
                    logger.warning("饮水提取失败: %s", exc)
                if diet_data or water_data:
                    agent.last_extract_result = {"diet_data": diet_data, "water_data": water_data}
                else:
                    agent.last_extract_result = {"diet_data": None, "water_data": None}

            threading.Thread(target=_legacy_extract, daemon=True, name="extract_task").start()
            return

        def _run_extract():
            try:
                t0 = time.monotonic()
                result = extractor.extract_only(
                    user_id=agent.user_id,
                    user_message=user_message,
                    ai_response=ai_response,
                )
                agent.last_extract_result = result or {"diet_data": None, "water_data": None}
                logger.info("后台提取完成 耗时=%.0fms has_diet=%s has_water=%s",
                            (time.monotonic() - t0) * 1000,
                            bool(result and result.get("diet_data")),
                            bool(result and result.get("water_data")))
            except Exception as exc:
                logger.warning("后台提取失败: %s", exc)
                agent.last_extract_result = {"diet_data": None, "water_data": None}

        threading.Thread(target=_run_extract, daemon=True, name="extract_task").start()

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
