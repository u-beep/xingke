"""合并提取器 — 一次 LLM 调用同时识别饮食与饮水记录。

原先饮食、饮水各自独立调用一次 LLM（串行 2 次往返，阻塞主回复返回），
本模块把两份提示词合并为一次调用，LLM 往返直接减半；
LLM 失败时分别回退到各自的规则引擎。
"""

import json
import logging
from typing import Optional

from .diet_extractor import DietExtractor
from .hydration_extractor import HydrationExtractor

logger = logging.getLogger(__name__)


# 合并提示词：一次调用同时判断饮食与饮水
_COMBINED_PROMPT = """你是一个健康记录提取助手。请分析用户的发言和AI的回复，同时完成两项判断：
1. 用户是否在记录/报告自己吃了什么食物（饮食记录）
2. 用户是否在报告自己喝了多少水或饮料（饮水记录）

用户发言："{user_message}"
AI回复："{ai_response}"

已知食物营养数据库（每100g）：
{food_database}

必须严格按以下JSON格式输出，不要输出其他内容：

{{
  "diet": {{
    "has_diet_record": true/false,
    "reason": "判断理由",
    "foods": [
      {{
        "food_name": "食物名称",
        "meal_type": "breakfast/lunch/dinner/snack",
        "amount_g": 估算分量克数,
        "calories": 估算热量kcal,
        "protein_g": 蛋白质g,
        "carbs_g": 碳水g,
        "fat_g": 脂肪g
      }}
    ],
    "total_calories": 总热量
  }},
  "water": {{
    "has_water_record": true/false,
    "reason": "判断理由",
    "amount_ml": 估算饮水量毫升数,
    "drink_type": "water/tea/coffee/juice/milk/soup/other",
    "description": "简短描述，如'一杯水 250ml'"
  }}
}}

注意：
1. 饮食：只有用户明确说了"吃了/喝了/记录"等表述时才设置 has_diet_record=true；如果用户只是询问食物热量但没说自己吃了，则为 false
2. 饮食的热量和营养素基于食物数据库和估算分量计算，AI回复中的数据优先；meal_type 根据时间和上下文判断，无法判断时用 "snack"
3. 饮水：只有用户明确说了"喝了/喝"等表述且与饮料相关时才设置 has_water_record=true；喝酒不算饮水；白开水/纯净水/矿泉水都用 "water"，茶类 "tea"，咖啡 "coffee"，果汁 "juice"，牛奶 "milk"，汤 "soup"，其他 "other"
4. 饮水量优先使用用户消息中明确给出的毫升数；若未明确给出，根据"一杯约250ml、一瓶约500ml、一口约30ml"等常识估算
5. 两项判断相互独立，可能同时为 true（如"吃了一个苹果，喝了杯牛奶"），也可能同时为 false
"""


class CombinedExtractor:
    """饮食+饮水合并提取器。

    在对话结束后，用一次 LLM 调用同时提取饮食与饮水记录，
    返回结构化数据，交由前端确认后再写入数据库（不自动入库）。
    """

    # 饮食记录预筛关键词（与 DietExtractor 保持一致）
    DIET_KEYWORDS = [
        "吃了", "喝了", "吃", "喝", "摄入", "记录", "打卡",
        "早餐", "午餐", "晚餐", "加餐", "零食", "宵夜", "点心",
        "早饭", "午饭", "晚饭", "代餐",
        "一个", "一包", "一杯", "一碗", "一盘", "一份", "两个", "三片",
        "今天吃", "刚吃", "刚喝", "中午吃", "晚上吃", "早上吃",
    ]

    @classmethod
    def _needs_diet_check(cls, user_message: str) -> bool:
        return any(kw in user_message for kw in cls.DIET_KEYWORDS)

    @classmethod
    def _needs_water_check(cls, user_message: str) -> bool:
        water = HydrationExtractor
        if not any(kw in user_message for kw in water.WATER_KEYWORDS):
            return False
        # 饮酒不算饮水
        if any(kw in user_message for kw in water.EXCLUDE_KEYWORDS):
            return False
        return True

    def __init__(self, gateway=None):
        """初始化合并提取器。

        Args:
            gateway: 模型网关实例
        """
        self.gateway = gateway
        # 复用各自的规则引擎与食物数据库
        self._diet = DietExtractor(gateway=gateway)
        self._water = HydrationExtractor(gateway=gateway)

    def extract_only(
        self,
        user_id: str,
        user_message: str,
        ai_response: str,
    ) -> Optional[dict]:
        """一次性提取饮食与饮水数据（不写入数据库）。

        Returns:
            {"diet_data": {...}|None, "water_data": {...}|None} 或 None
            - diet_data: {"foods": [...], "total_calories": ...}
            - water_data: {"amount_ml": float, "drink_type": str, "description": str}
        """
        # 双重预筛：两类关键词都不命中 → 直接跳过（大多数闲聊场景零 LLM 调用）
        need_diet = self._needs_diet_check(user_message)
        need_water = self._needs_water_check(user_message)
        if not need_diet and not need_water:
            logger.debug("用户消息不含饮食/饮水关键词，跳过提取")
            return None

        # 一次 LLM 调用同时提取两类记录
        if self.gateway:
            try:
                food_db_str = json.dumps(self._diet._food_db, ensure_ascii=False, indent=2)
                prompt = _COMBINED_PROMPT.format(
                    user_message=user_message,
                    ai_response=ai_response[:500],
                    food_database=food_db_str,
                )
                response = self.gateway.complete(
                    prompt,
                    max_new_tokens=1024,
                    user_id=user_id,
                    scene="record_extract",
                )
                result = self._parse_response(response)
                if result:
                    diet_data = self._normalize_diet(result.get("diet"))
                    water_data = self._normalize_water(result.get("water"))
                    if diet_data or water_data:
                        return {"diet_data": diet_data, "water_data": water_data}
                    # LLM 明确判断无记录 → 结束（保持原提取器语义，不重复走规则引擎）
                    return None
            except Exception as exc:
                logger.warning("LLM 合并提取失败，回退规则引擎: %s", exc)

        # 规则引擎兜底（LLM 调用失败或解析失败时）
        diet_data = None
        water_data = None
        if need_diet:
            foods = self._diet._rule_based_extract_foods(user_message)
            if foods:
                total_cal = sum(f.get("calories", 0) for f in foods)
                diet_data = {"foods": foods, "total_calories": round(total_cal, 1)}
        if need_water:
            water_data = self._water._rule_based_extract(user_message)

        if diet_data or water_data:
            return {"diet_data": diet_data, "water_data": water_data}
        return None

    @staticmethod
    def _normalize_diet(diet: Optional[dict]) -> Optional[dict]:
        """规范化 LLM 返回的饮食数据。"""
        if not isinstance(diet, dict):
            return None
        if not diet.get("has_diet_record") or not diet.get("foods"):
            return None
        foods = [f for f in diet["foods"] if isinstance(f, dict) and f.get("food_name")]
        if not foods:
            return None
        return {
            "foods": foods,
            "total_calories": diet.get("total_calories", 0),
        }

    @staticmethod
    def _normalize_water(water: Optional[dict]) -> Optional[dict]:
        """规范化 LLM 返回的饮水数据。"""
        if not isinstance(water, dict):
            return None
        if not water.get("has_water_record") or not water.get("amount_ml"):
            return None
        try:
            amount_ml = float(water["amount_ml"])
        except (TypeError, ValueError):
            return None
        if amount_ml <= 0:
            return None
        return {
            "amount_ml": round(amount_ml, 1),
            "drink_type": water.get("drink_type", "water") or "water",
            "description": water.get("description", "") or f"{amount_ml:.0f}ml",
        }

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

        logger.warning("无法解析合并提取结果: %s", str(response)[:200])
        return None
