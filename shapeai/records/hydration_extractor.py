"""饮水自动提取器 — 从对话中识别用户饮水记录。

在每轮对话结束后，让 LLM 分析用户消息和 AI 回复，
判断用户是否在报告自己喝了多少水（或其他饮料）。
如果是，提取饮水量（毫升）和饮料类型，交由前端确认后再写入数据库。
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# 让模型从对话中提取饮水记录的提示词
_EXTRACT_PROMPT = """你是一个饮水记录提取助手。请分析用户的发言和AI的回复，判断用户是否在报告自己喝了多少水（或其他饮料如茶、咖啡、果汁、汤等）。

用户发言："{user_message}"
AI回复："{ai_response}"

请判断用户是否在报告自己喝了饮料。如果是，请提取饮水量。
必须严格按以下JSON格式输出，不要输出其他内容：

{{
  "has_water_record": true/false,
  "reason": "判断理由",
  "amount_ml": 估算饮水量毫升数,
  "drink_type": "water/tea/coffee/juice/milk/soup/other",
  "description": "简短描述，如'一杯水 250ml'"
}}

注意：
1. 只有当用户明确说了"喝了/喝/饮"等表述且与饮料相关时才设置 has_water_record=true
2. 优先使用用户消息中明确给出的毫升数；若未明确给出，根据"一杯约250ml、一瓶约500ml、一口约30ml"等常识估算
3. drink_type：白开水/纯净水/矿泉水都用 "water"；茶类用 "tea"；咖啡用 "coffee"；果汁用 "juice"；牛奶用 "milk"；汤类用 "soup"；其他用 "other"
4. 如果用户只是询问"应该喝多少水"但没说自己喝了，has_water_record=false
"""


class HydrationExtractor:
    """饮水自动提取器。

    在对话结束后，使用 LLM 从对话内容中提取饮水记录，
    返回结构化数据，交由前端确认后再写入数据库（不自动入库）。
    """

    # 触发提取的关键词
    WATER_KEYWORDS = [
        "喝了", "喝", "饮", "饮水", "喝水", "补充水分",
        "杯水", "瓶水", "杯茶", "杯咖啡", "杯果汁", "杯牛奶",
        "一瓶", "一杯", "一壶", "一碗汤",
        "今天喝", "刚喝", "早上喝", "中午喝", "晚上喝",
    ]

    # 非饮水记录的干扰词（含这些时跳过）
    EXCLUDE_KEYWORDS = ["喝了酒", "喝酒", "啤酒", "白酒", "红酒"]

    def __init__(self, gateway=None):
        """初始化饮水提取器。

        Args:
            gateway: 模型网关实例
        """
        self.gateway = gateway

    def extract_only(
        self,
        user_id: str,
        user_message: str,
        ai_response: str,
    ) -> Optional[dict]:
        """只提取饮水量数据，不写入数据库（供前端确认后再写入）。

        Returns:
            {"amount_ml": float, "drink_type": str, "description": str} 或 None
        """
        # 快速预检：必须包含饮水关键词
        if not any(kw in user_message for kw in self.WATER_KEYWORDS):
            return None
        # 排除饮酒
        if any(kw in user_message for kw in self.EXCLUDE_KEYWORDS):
            return None

        # 先尝试 LLM 提取
        if self.gateway:
            try:
                prompt = _EXTRACT_PROMPT.format(
                    user_message=user_message,
                    ai_response=ai_response[:500],
                )
                response = self.gateway.complete(
                    prompt,
                    max_new_tokens=512,
                    user_id=user_id,
                    scene="water_extract",
                )
                result = self._parse_response(response)
                if result and result.get("has_water_record") and result.get("amount_ml"):
                    amount_ml = float(result["amount_ml"])
                    if amount_ml <= 0:
                        return None
                    return {
                        "amount_ml": round(amount_ml, 1),
                        "drink_type": result.get("drink_type", "water") or "water",
                        "description": result.get("description", "") or f"{amount_ml:.0f}ml",
                    }
            except Exception as exc:
                logger.warning("LLM 饮水提取失败，使用规则引擎: %s", exc)

        # 规则引擎兜底
        return self._rule_based_extract(user_message)

    def _rule_based_extract(self, user_message: str) -> Optional[dict]:
        """规则引擎兜底：用关键词+量词估算饮水量。"""
        # 单位 -> 毫升估算
        unit_ml = {
            "杯": 250.0,
            "瓶": 500.0,
            "壶": 800.0,
            "碗": 200.0,
            "大杯": 400.0,
            "小杯": 150.0,
        }

        # 饮料类型识别。用户若明确写了“水/喝水/xxxml 水”，优先按水记录；
        # 避免同一句还提到牛奶、咖啡等食物时覆盖本次实际喝水的类型。
        drink_type = "water"
        explicit_water = any(kw in user_message for kw in [
            "白开水", "纯净水", "矿泉水", "喝水", "饮水",
        ]) or bool(re.search(r"\d+(?:\.\d+)?\s*(?:ml|mL|ML|毫升|cc)\s*(?:的)?水", user_message))
        if not explicit_water:
            if any(kw in user_message for kw in ["茶", "绿茶", "红茶", "乌龙", "花茶"]):
                drink_type = "tea"
            elif "咖啡" in user_message:
                drink_type = "coffee"
            elif any(kw in user_message for kw in ["果汁", "橙汁", "苹果汁"]):
                drink_type = "juice"
            elif "牛奶" in user_message or "酸奶" in user_message:
                drink_type = "milk"
            elif "汤" in user_message:
                drink_type = "soup"

        # 优先匹配用户消息中明确给出的毫升数（如"喝了300ml水"、"500毫升"）
        ml_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:ml|mL|ML|毫升|cc)', user_message)
        if ml_match:
            amount_ml = float(ml_match.group(1))
            if amount_ml > 0:
                return {
                    "amount_ml": round(amount_ml, 1),
                    "drink_type": drink_type,
                    "description": f"{drink_type} {amount_ml:.0f}ml",
                }

        # 匹配 "数字 + 单位"
        num_unit_match = re.search(
            r'(\d+(?:\.\d+)?)\s*(大杯|小杯|杯|瓶|壶|碗)', user_message
        )
        if num_unit_match:
            portion = float(num_unit_match.group(1))
            unit = num_unit_match.group(2)
            amount_ml = portion * unit_ml.get(unit, 250.0)
            if amount_ml > 0:
                return {
                    "amount_ml": round(amount_ml, 1),
                    "drink_type": drink_type,
                    "description": f"{portion:g}{unit}{drink_type} {amount_ml:.0f}ml",
                }

        # 无明确量词时，单次出现"喝了一杯/一瓶"按 250ml 兜底
        if re.search(r'喝了.{0,4}(杯|瓶)', user_message):
            amount_ml = 250.0
            return {
                "amount_ml": amount_ml,
                "drink_type": drink_type,
                "description": f"{drink_type} 约{amount_ml:.0f}ml",
            }

        return None

    @staticmethod
    def _parse_response(response: str) -> Optional[dict]:
        """解析模型返回的 JSON。"""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        try:
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1:
                return json.loads(response[start:end + 1])
        except json.JSONDecodeError:
            pass

        logger.warning("无法解析饮水提取结果: %s", response[:200])
        return None
