"""饮食自动提取器 — 从对话中自动识别食物并记录热量。

在每轮对话结束后，让 LLM 分析用户消息和 AI 回复，
判断用户是否在记录饮食。如果是，提取食物名称、分量、热量、营养素，
自动写入 DietStore，更新今日热量摄入表。
"""

import json
import logging
from typing import Optional

from .diet_store import DietStore, DietRecord

logger = logging.getLogger(__name__)

# 让模型从对话中提取饮食记录的提示词
_EXTRACT_PROMPT = """你是一个饮食记录提取助手。请分析用户的发言和AI的回复，判断用户是否在记录/报告自己吃了什么食物。

用户发言："{user_message}"
AI回复："{ai_response}"

已知食物营养数据库（每100g）：
{food_database}

请判断用户是否在报告自己吃了食物。如果是，请提取每样食物的信息。
必须严格按以下JSON格式输出，不要输出其他内容：

{{
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
  "total_calories": 总热量,
  "message": "可选的确认消息，如'已记录：苹果104kcal、牛奶135kcal，今日累计239kcal'"
}}

注意：
1. 只有当用户明确说了"吃了/喝了/记录"等表述时才设置 has_diet_record=true
2. 热量和营养素基于食物数据库和估算分量计算，AI回复中的数据优先
3. meal_type 根据时间和上下文判断，无法判断时用 "snack"
4. 如果用户只是询问食物热量但没有说"吃了"，has_diet_record=false
5. 如果AI回复中已经有热量估算表格，直接使用那些数据
"""


class DietExtractor:
    """饮食自动提取器。

    在对话结束后，使用 LLM 从对话内容中提取饮食记录，
    自动写入 DietStore，更新今日热量摄入。
    """

    def __init__(self, gateway=None):
        """初始化饮食提取器。

        Args:
            gateway: 模型网关实例
        """
        self.gateway = gateway
        self.store = DietStore()
        # 内置食物数据库用于提示词
        from ..config import FOOD_DATABASE
        self._food_db = FOOD_DATABASE

    def extract_only(
        self,
        user_id: str,
        user_message: str,
        ai_response: str,
    ) -> Optional[dict]:
        """只提取食物数据，不写入数据库（供前端确认后再写入）。

        Returns:
            {"foods": [...], "total_calories": ...} 或 None
        """
        # 快速预检
        diet_keywords = [
            "吃了", "喝了", "吃", "喝", "摄入", "记录", "打卡",
            "早餐", "午餐", "晚餐", "加餐", "零食", "宵夜", "点心",
            "早饭", "午饭", "晚饭", "代餐",
            "一个", "一包", "一杯", "一碗", "一盘", "一份", "两个", "三片",
            "今天吃", "刚吃", "刚喝", "中午吃", "晚上吃", "早上吃",
        ]
        if not any(kw in user_message for kw in diet_keywords):
            return None

        # 先尝试 LLM 提取
        if self.gateway:
            try:
                food_db_str = json.dumps(self._food_db, ensure_ascii=False, indent=2)
                prompt = _EXTRACT_PROMPT.format(
                    user_message=user_message,
                    ai_response=ai_response[:500],
                    food_database=food_db_str,
                )
                response = self.gateway.complete(
                    prompt,
                    max_new_tokens=1024,
                    user_id=user_id,
                    scene="diet_extract",
                )
                result = self._parse_response(response)
                if result and result.get("has_diet_record") and result.get("foods"):
                    return {
                        "foods": result["foods"],
                        "total_calories": result.get("total_calories", 0),
                    }
            except Exception as exc:
                logger.warning("LLM 饮食提取失败，使用规则引擎: %s", exc)

        # 规则引擎兜底
        foods = self._rule_based_extract_foods(user_message)
        if foods:
            total_cal = sum(f.get("calories", 0) for f in foods)
            return {"foods": foods, "total_calories": round(total_cal, 1)}

        return None

    def check_and_record(
        self,
        user_id: str,
        user_message: str,
        ai_response: str,
    ) -> Optional[str]:
        """检查对话是否包含饮食记录，如果是则自动提取并保存。

        Args:
            user_id: 用户ID
            user_message: 用户原始消息
            ai_response: AI 回复内容
        Returns:
            如果有记录被保存，返回确认消息；否则返回 None
        """
        if not self.gateway:
            logger.debug("未配置模型网关，跳过饮食提取")
            return None

        logger.info("饮食提取开始: user=%s msg=%s", user_id, user_message[:50])

        # 快速预检：用户消息中是否包含饮食相关关键词
        diet_keywords = [
            # 明确动作词
            "吃了", "喝了", "吃", "喝", "摄入", "记录", "打卡",
            # 餐次词
            "早餐", "午餐", "晚餐", "加餐", "零食", "宵夜", "点心",
            "早饭", "午饭", "晚饭", "代餐",
            # 量词+食物常见组合
            "一个", "一包", "一杯", "一碗", "一盘", "一份", "两个", "三片",
            # 其他
            "今天吃", "刚吃", "刚喝", "中午吃", "晚上吃", "早上吃",
        ]
        if not any(kw in user_message for kw in diet_keywords):
            logger.debug("用户消息不含饮食记录关键词，跳过提取")
            return None

        # 构建提取提示
        food_db_str = json.dumps(self._food_db, ensure_ascii=False, indent=2)
        prompt = _EXTRACT_PROMPT.format(
            user_message=user_message,
            ai_response=ai_response[:500],  # 截断防止prompt过长
            food_database=food_db_str,
        )

        try:
            response = self.gateway.complete(
                prompt,
                max_new_tokens=1024,
                user_id=user_id,
                scene="diet_extract",
            )
            result = self._parse_response(response)

            if not result or not result.get("has_diet_record"):
                logger.debug("用户 %s 的对话不含饮食记录: %s",
                             user_id, result.get("reason", "无") if result else "解析失败")
                # LLM 解析失败或判断无记录 → 尝试规则引擎兼底
                return self._rule_based_extract(user_id, user_message, ai_response)

            # 提取食物列表并写入数据库
            foods = result.get("foods", [])
            if not foods:
                # LLM 判断有记录但未提取出食物 → 尝试规则引擎
                return self._rule_based_extract(user_id, user_message, ai_response)

            saved_count = 0
            total_calories = 0
            for food in foods:
                record = DietRecord(
                    user_id=user_id,
                    meal_type=food.get("meal_type", "snack"),
                    food_name=food.get("food_name", ""),
                    amount_g=food.get("amount_g"),
                    calories=food.get("calories"),
                    protein_g=food.get("protein_g"),
                    carbs_g=food.get("carbs_g"),
                    fat_g=food.get("fat_g"),
                )
                record_id = self.store.add_record(record)
                if record_id:
                    saved_count += 1
                    total_calories += food.get("calories", 0)

            if saved_count > 0:
                # 获取今日累计
                today_summary = self.store.get_today_summary(user_id)
                today_total = today_summary.get("total_calories", 0)

                msg = result.get("message", "")
                if not msg:
                    food_names = "、".join(f.get("food_name", "") for f in foods)
                    msg = f"已记录饮食：{food_names}（{total_calories:.0f}kcal），今日累计摄入 {today_total:.0f}kcal"

                logger.info("用户 %s 饮食记录已自动保存: %d 项, 本次 %dkcal, 今日累计 %dkcal",
                            user_id, saved_count, total_calories, today_total)
                return msg

        except Exception as exc:
            logger.warning("饮食提取失败: %s", exc)
            # LLM 调用失败 → 尝试规则引擎兼底
            return self._rule_based_extract(user_id, user_message, ai_response)

    def _rule_based_extract(
        self,
        user_id: str,
        user_message: str,
        ai_response: str,
    ) -> Optional[str]:
        """规则引擎兼底：当 LLM 提取失败时，用关键词匹配食物数据库。

        直接从用户消息中匹配内置食物数据库的食物名称，
        根据量词估算分量，计算热量和营养素。
        """
        import re

        matched_foods = []
        for food_name, nutrition in self._match_foods_by_name(user_message, self._food_db):
            amount_g = 100  # 默认 100g
            portion = 1.0

            # 匹配量词
            # 查找食物名前 10 个字符内是否有量词
            idx = user_message.find(food_name)
            context_before = user_message[max(0, idx - 10):idx]

            # 数字+量词
            num_match = re.search(r'(\d+)\s*(?:个|包|杯|碗|盘|份|片|块|条|根|瓶|袋|盒)', context_before)
            if num_match:
                portion = float(num_match.group(1))
            else:
                # 中文量词
                if '半' in context_before:
                    portion = 0.5
                elif '两' in context_before or '双' in context_before:
                    portion = 2.0
                elif '大' in context_before:
                    portion = 1.5
                elif '小' in context_before:
                    portion = 0.5

            # 特殊食物分量估算
            if food_name in ("苹果", "鸡蛋", "橙子", "橘子"):
                amount_g = portion * 150  # 一个约 150g
            elif food_name in ("牛奶",):
                amount_g = portion * 250  # 一杯/包约 250g
            elif food_name in ("米饭", "面条"):
                amount_g = portion * 200  # 一碗约 200g
            elif food_name in ("馒头",):
                amount_g = portion * 100  # 一个约 100g
            else:
                amount_g = portion * 100

            # 计算营养素（基于每100g的数据按比例缩放）
            ratio = amount_g / 100
            calories = round(nutrition["calories"] * ratio, 1)
            protein = round(nutrition["protein"] * ratio, 1)
            carbs = round(nutrition["carbs"] * ratio, 1)
            fat = round(nutrition["fat"] * ratio, 1)

            # 判断餐次
            meal_type = "snack"
            if any(kw in user_message for kw in ["早餐", "早饭", "早上吃"]):
                meal_type = "breakfast"
            elif any(kw in user_message for kw in ["午餐", "午饭", "中午吃"]):
                meal_type = "lunch"
            elif any(kw in user_message for kw in ["晚餐", "晚饭", "晚上吃", "宵夜"]):
                meal_type = "dinner"

            matched_foods.append({
                "food_name": food_name,
                "meal_type": meal_type,
                "amount_g": amount_g,
                "calories": calories,
                "protein_g": protein,
                "carbs_g": carbs,
                "fat_g": fat,
            })

        if not matched_foods:
            return None

        return self._save_foods(user_id, matched_foods)

    @staticmethod
    def _match_foods_by_name(user_message: str, food_db: dict) -> list[tuple[str, dict]]:
        """按名称匹配用户消息中提到的食物。

        匹配规则：
        1. 完整食物名出现在消息中 → 直接命中；
        2. 单字兜底：食物名尾字出现在消息中 → 命中（如说“蛋”指“鸡蛋”）。
           兜底前先把已完整命中的食物名从消息中剔除，避免“米饭”的“米”
           被“玉米”的尾字规则误命中（用户没吃玉米却多出一条记录）。
        """
        matched: list[tuple[str, dict]] = []
        matched_short_names = set()

        exact_food_names = {
            food_name for food_name in food_db
            if food_name in user_message
        }
        exact_suffixes = {n[-1:] for n in exact_food_names if len(n) >= 2}
        # 剔除已完整命中的食物名后，剩余文本只用于单字兜底
        remainder = user_message
        for name in sorted(exact_food_names, key=len, reverse=True):
            remainder = remainder.replace(name, " ")

        for food_name, nutrition in food_db.items():
            if food_name in exact_food_names:
                matched.append((food_name, nutrition))
                continue
            if len(food_name) >= 2 and food_name[-1] in remainder:
                short_name = food_name[-1:]
                if (
                    short_name not in exact_suffixes
                    and short_name not in matched_short_names
                ):
                    matched.append((food_name, nutrition))
                    matched_short_names.add(short_name)
        return matched

    def _rule_based_extract_foods(self, user_message: str) -> list:
        """规则引擎：只提取食物列表，不写入数据库。"""
        import re

        matched_foods = []
        for food_name, nutrition in self._match_foods_by_name(user_message, self._food_db):
            amount_g = 100
            portion = 1.0
            idx = user_message.find(food_name)
            context_before = user_message[max(0, idx - 10):idx]
            num_match = re.search(r'(\d+)\s*(?:个|包|杯|碗|盘|份|片|块|条|根|瓶|袋|盒)', context_before)
            if num_match:
                portion = float(num_match.group(1))
            else:
                if '半' in context_before:
                    portion = 0.5
                elif '两' in context_before or '双' in context_before:
                    portion = 2.0
                elif '大' in context_before:
                    portion = 1.5
                elif '小' in context_before:
                    portion = 0.5

            if food_name in ("苹果", "鸡蛋", "橙子", "橘子"):
                amount_g = portion * 150
            elif food_name in ("牛奶",):
                amount_g = portion * 250
            elif food_name in ("米饭", "面条"):
                amount_g = portion * 200
            elif food_name in ("馒头",):
                amount_g = portion * 100
            else:
                amount_g = portion * 100

            ratio = amount_g / 100
            meal_type = "snack"
            if any(kw in user_message for kw in ["早餐", "早饭", "早上吃"]):
                meal_type = "breakfast"
            elif any(kw in user_message for kw in ["午餐", "午饭", "中午吃"]):
                meal_type = "lunch"
            elif any(kw in user_message for kw in ["晚餐", "晚饭", "晚上吃", "宵夜"]):
                meal_type = "dinner"

            matched_foods.append({
                "food_name": food_name,
                "meal_type": meal_type,
                "amount_g": round(amount_g, 1),
                "calories": round(nutrition["calories"] * ratio, 1),
                "protein_g": round(nutrition["protein"] * ratio, 1),
                "carbs_g": round(nutrition["carbs"] * ratio, 1),
                "fat_g": round(nutrition["fat"] * ratio, 1),
            })

        return matched_foods

    def _save_foods(self, user_id: str, foods: list) -> Optional[str]:
        """将食物列表写入数据库并返回确认消息。"""
        saved_count = 0
        total_calories = 0
        for food in foods:
            record = DietRecord(
                user_id=user_id,
                meal_type=food["meal_type"],
                food_name=food["food_name"],
                amount_g=food["amount_g"],
                calories=food["calories"],
                protein_g=food["protein_g"],
                carbs_g=food["carbs_g"],
                fat_g=food["fat_g"],
            )
            record_id = self.store.add_record(record)
            if record_id:
                saved_count += 1
                total_calories += food["calories"]

        if saved_count > 0:
            today_summary = self.store.get_today_summary(user_id)
            today_total = today_summary.get("total_calories", 0)
            food_names = "、".join(f["food_name"] for f in foods)
            msg = f"已记录饮食：{food_names}（{total_calories:.0f}kcal），今日累计摄入 {today_total:.0f}kcal"
            logger.info("用户 %s 饮食记录已自动保存(规则引擎): %d 项, 本次 %dkcal, 今日累计 %dkcal",
                        user_id, saved_count, total_calories, today_total)
            return msg

        return None

    @staticmethod
    def _parse_response(response: str) -> Optional[dict]:
        """解析模型返回的 JSON。"""
        try:
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

        logger.warning("无法解析饮食提取结果: %s", response[:200])
        return None
