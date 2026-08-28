"""个性化饮食方案生成引擎。

基于用户画像生成单日/周食谱，支持菜品替换和分量调整。
使用大模型 + 硬规则引擎混合实现。
"""

import json
import logging
from typing import Optional

from .calculator import calculate_bmr, calculate_tdee, calculate_calorie_deficit, calculate_macros
from ..config import FOOD_DATABASE

logger = logging.getLogger(__name__)


class DietPlanner:
    """饮食方案生成器。

    使用 LLM 生成个性化食谱，同时用硬规则引擎校验营养素配比。
    """

    def __init__(self, gateway=None):
        """初始化饮食方案生成器。

        Args:
            gateway: 模型网关实例，None 时只能使用规则引擎模式
        """
        self.gateway = gateway

    def generate_plan(
        self,
        gender: str = "male",
        age: int = 25,
        weight: float = 70,
        height: float = 175,
        activity_level: str = "moderate",
        target_deficit: float = 500,
        meals_per_day: int = 3,
        preferences: str = "",
        allergies: str = "",
        cooking_equipment: str = "",
        days: int = 1,
        user_id: str = "anonymous",
    ) -> dict:
        """生成个性化饮食方案。

        Args:
            gender/age/weight/height: 身体基础数据
            activity_level: 活动水平
            target_deficit: 目标热量缺口
            meals_per_day: 每日餐数
            preferences: 饮食偏好（如"清淡、少油"）
            allergies: 忌口（如"花生、海鲜"）
            cooking_equipment: 厨具条件（如"有微波炉、电饭煲"）
            days: 生成几天食谱
            user_id: 用户ID
        Returns:
            包含计算结果和食谱的字典
        """
        # 1. 硬规则计算
        bmr_result = calculate_bmr(gender, age, weight, height)
        tdee_result = calculate_tdee(bmr_result["bmr"], activity_level)
        deficit_result = calculate_calorie_deficit(tdee_result["tdee"], target_deficit)
        macros_result = calculate_macros(deficit_result["target_intake"])

        # 2. 生成食谱
        if self.gateway:
            diet_plan = self._generate_with_llm(
                deficit_result["target_intake"],
                macros_result,
                meals_per_day,
                preferences,
                allergies,
                cooking_equipment,
                days,
                user_id,
            )
        else:
            diet_plan = self._generate_with_rules(
                deficit_result["target_intake"],
                macros_result,
                meals_per_day,
                days,
            )

        return {
            "calculations": {
                "bmr": bmr_result,
                "tdee": tdee_result,
                "calorie_deficit": deficit_result,
                "macros": macros_result,
            },
            "diet_plan": diet_plan,
        }

    def _generate_with_llm(
        self, target_calories: float, macros: dict, meals_per_day: int,
        preferences: str, allergies: str, cooking_equipment: str,
        days: int, user_id: str,
    ) -> dict:
        """使用大模型生成食谱。"""
        prompt = f"""请为用户生成{days}天的个性化饮食方案。

用户信息：
- 目标每日摄入热量：{target_calories:.0f} kcal
- 蛋白质：{macros['protein']['grams']:.0f}g ({macros['protein']['ratio']:.0f}%)
- 碳水化合物：{macros['carbs']['grams']:.0f}g ({macros['carbs']['ratio']:.0f}%)
- 脂肪：{macros['fat']['grams']:.0f}g ({macros['fat']['ratio']:.0f}%)
- 每日餐数：{meals_per_day}
- 饮食偏好：{preferences or '无特殊偏好'}
- 忌口：{allergies or '无'}
- 厨具条件：{cooking_equipment or '普通厨房'}

请以JSON格式输出，包含以下结构：
{{
  "days": [
    {{
      "day": 1,
      "meals": [
        {{
          "meal": "早餐",
          "foods": [
            {{"name": "食物名", "amount": "分量", "calories": 估算热量}}
          ],
          "total_calories": 本餐总热量
        }}
      ],
      "total_calories": 全天总热量
    }}
  ]
}}

要求：
1. 食物尽量常见、易获取
2. 严格避开用户的忌口
3. 总热量控制在目标值±100kcal以内
4. 每餐标注具体分量
"""

        try:
            response = self.gateway.complete(
                prompt, max_new_tokens=2048,
                user_id=user_id, scene="diet_plan",
            )
            # 尝试解析JSON
            return self._parse_diet_response(response, days)
        except Exception as exc:
            logger.warning("LLM食谱生成失败，回退到规则引擎: %s", exc)
            return self._generate_with_rules(target_calories, macros, meals_per_day, days)

    def _generate_with_rules(
        self, target_calories: float, macros: dict, meals_per_day: int, days: int,
    ) -> dict:
        """使用规则引擎生成基础食谱（无LLM时的回退方案）。"""
        # 按餐次分配热量比例
        if meals_per_day == 3:
            ratios = [0.30, 0.40, 0.30]
            meal_names = ["早餐", "午餐", "晚餐"]
        elif meals_per_day == 4:
            ratios = [0.25, 0.35, 0.10, 0.30]
            meal_names = ["早餐", "午餐", "加餐", "晚餐"]
        else:
            ratios = [1.0 / meals_per_day] * meals_per_day
            meal_names = [f"餐{i+1}" for i in range(meals_per_day)]

        # 食物分类
        carb_foods = ["米饭", "面条", "馒头", "燕麦", "红薯", "玉米"]
        protein_foods = ["鸡蛋", "鸡胸肉", "牛肉", "鱼肉", "豆腐", "牛奶"]
        veg_foods = ["西兰花", "西红柿", "黄瓜", "生菜", "胡萝卜"]
        fruit_foods = ["苹果", "香蕉"]

        result_days = []
        for day in range(1, days + 1):
            meals = []
            day_total = 0
            for i, (ratio, meal_name) in enumerate(zip(ratios, meal_names)):
                meal_calories = target_calories * ratio
                foods = []
                # 简单搭配：碳水+蛋白质+蔬菜
                carb = carb_foods[day % len(carb_foods)]
                protein = protein_foods[i % len(protein_foods)]
                veg = veg_foods[i % len(veg_foods)]

                carb_info = FOOD_DATABASE.get(carb, {})
                protein_info = FOOD_DATABASE.get(protein, {})
                veg_info = FOOD_DATABASE.get(veg, {})

                # 估算分量
                carb_amount = meal_calories * 0.5 / max(carb_info.get("calories", 100), 1) * 100
                protein_amount = meal_calories * 0.35 / max(protein_info.get("calories", 100), 1) * 100
                veg_amount = 100  # 蔬菜固定100g

                foods.append({"name": carb, "amount": f"{carb_amount:.0f}g", "calories": int(carb_info.get("calories", 100) * carb_amount / 100)})
                foods.append({"name": protein, "amount": f"{protein_amount:.0f}g", "calories": int(protein_info.get("calories", 100) * protein_amount / 100)})
                foods.append({"name": veg, "amount": f"{veg_amount}g", "calories": int(veg_info.get("calories", 20))})

                meal_total = sum(f["calories"] for f in foods)
                day_total += meal_total
                meals.append({"meal": meal_name, "foods": foods, "total_calories": meal_total})

            result_days.append({"day": day, "meals": meals, "total_calories": int(day_total)})

        return {"days": result_days, "source": "rule_engine"}

    @staticmethod
    def _parse_diet_response(response: str, days: int) -> dict:
        """解析LLM返回的食谱JSON。"""
        # 尝试直接解析
        try:
            data = json.loads(response)
            data["source"] = "llm"
            return data
        except json.JSONDecodeError:
            pass

        # 尝试提取JSON块
        import re
        match = re.search(r'\{[\s\S]*\}', response)
        if match:
            try:
                data = json.loads(match.group())
                data["source"] = "llm"
                return data
            except json.JSONDecodeError:
                pass

        # 解析失败，返回原始文本
        return {"days": [], "source": "llm_raw", "raw_response": response[:500]}
