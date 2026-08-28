"""用户偏好自动更新判断器。

根据用户提问，让 LLM 判断是否需要更新个人资料，
并提取需要更新的字段和值。
"""

import json
import logging
from typing import Optional

from .profile_store import ProfileStore, UserProfile

logger = logging.getLogger(__name__)

# 让模型判断是否需要更新资料的系统提示
_JUDGE_PROMPT = """你是一个用户偏好提取助手。请分析用户的最新发言，判断用户是否在提供或更新自己的个人信息。

需要关注的字段包括：
- 身高(height_cm, 单位cm)
- 体重(weight_kg, 单位kg)
- 年龄(age)
- 性别(gender: male/female)
- 目标体重(target_weight_kg, 单位kg)
- 运动频率(exercise_frequency: sedentary/light/moderate/active/very_active)
- 喜欢的运动(preferred_exercises: 列表)
- 运动目标(exercise_goals: 列表)
- 饮食限制(dietary_restrictions: 列表，如素食、过敏等)
- 喜欢的菜系(preferred_cuisines: 列表)
- 不喜欢的食物(disliked_foods: 列表)
- 每日餐数(meal_count_per_day)
- 健康目标(health_goal: lose_weight/maintain/gain_muscle)
- 目标日期(target_date)
- 平均睡眠(sleep_hours)
- 每日饮水目标(water_intake_ml)
- 备注(notes)

当前用户资料：
{current_profile}

用户最新发言："{user_message}"

请判断用户是否在更新个人信息。如果是，请提取需要更新的字段和值。
必须严格按以下JSON格式输出，不要输出其他内容：

{{
  "should_update": true/false,
  "reason": "判断理由",
  "updates": {{
    "字段名": "新值",
    ...
  }},
  "message_to_user": "可选的确认消息，如'已记录你的身高为175cm'"
}}

注意：
1. 只有当用户明确提供或修改信息时才设置 should_update=true
2. 数值字段直接给数字，列表字段给数组
3. 如果用户只是询问而不提供新信息，should_update=false
4. 不要猜测用户的意图，只提取明确陈述的信息
"""


class PreferenceUpdater:
    """偏好更新判断器。

    使用 LLM 判断用户发言是否包含个人信息更新，
    并自动提取和保存。
    """

    def __init__(self, gateway=None):
        self.gateway = gateway
        self.store = ProfileStore()

    def check_and_update(self, user_id: str, user_message: str) -> Optional[str]:
        """检查用户消息是否需要更新个人资料。

        Args:
            user_id: 用户ID
            user_message: 用户最新发言

        Returns:
            如果有更新，返回确认消息；否则返回 None
        """
        if not self.gateway:
            logger.debug("未配置模型网关，跳过偏好更新判断")
            return None

        # 获取当前资料
        profile = self.store.get(user_id)
        current_text = profile.to_context_text()

        # 构建判断提示
        prompt = _JUDGE_PROMPT.format(
            current_profile=current_text,
            user_message=user_message,
        )

        try:
            response = self.gateway.complete(
                prompt,
                max_new_tokens=1024,
                user_id=user_id,
                scene="profile_update_judge",
            )
            result = self._parse_response(response)

            if not result or not result.get("should_update"):
                logger.debug("用户 %s 的发言无需更新资料: %s", user_id, result.get("reason", "无需更新"))
                return None

            # 执行更新
            updates = result.get("updates", {})
            if updates:
                self._apply_updates(profile, updates)
                saved = self.store.save(profile)
                if saved:
                    logger.info("用户 %s 资料已更新: %s", user_id, updates)
                    return result.get("message_to_user", "已更新你的个人资料")

        except Exception as exc:
            logger.warning("偏好更新判断失败: %s", exc)

        return None

    @staticmethod
    def _parse_response(response: str) -> Optional[dict]:
        """解析模型返回的 JSON。"""
        try:
            # 尝试直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 块
        try:
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1:
                return json.loads(response[start:end + 1])
        except json.JSONDecodeError:
            pass

        logger.warning("无法解析偏好更新判断结果: %s", response[:200])
        return None

    @staticmethod
    def _apply_updates(profile: UserProfile, updates: dict):
        """将更新应用到 profile 对象。"""
        field_map = {
            "height_cm": float,
            "weight_kg": float,
            "age": int,
            "gender": str,
            "target_weight_kg": float,
            "exercise_frequency": str,
            "preferred_exercises": list,
            "exercise_goals": list,
            "dietary_restrictions": list,
            "preferred_cuisines": list,
            "disliked_foods": list,
            "meal_count_per_day": int,
            "health_goal": str,
            "target_date": str,
            "sleep_hours": float,
            "water_intake_ml": int,
            "notes": str,
        }

        for field, value in updates.items():
            if field not in field_map:
                logger.warning("未知字段: %s", field)
                continue
            if value is None:
                continue
            try:
                expected_type = field_map[field]
                if expected_type == list and not isinstance(value, list):
                    value = [value] if value else []
                elif expected_type in (int, float) and isinstance(value, str):
                    value = expected_type(value)
                setattr(profile, field, value)
            except (ValueError, TypeError) as exc:
                logger.warning("字段 %s 值转换失败: %s -> %s", field, value, exc)
