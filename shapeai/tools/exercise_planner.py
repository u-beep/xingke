"""运动计划生成引擎。

根据用户运动基础、可用时间、场地器械、目标部位生成训练计划。
支持动作难度适配、组数次数规划。
"""

import json
import logging

logger = logging.getLogger(__name__)

# 内置动作库（MVP版本）
EXERCISE_DATABASE = {
    "全身": [
        {"name": "深蹲", "difficulty": "beginner", "equipment": "none", "muscle": "腿/臀", "calories_per_set": 50},
        {"name": "俯卧撑", "difficulty": "beginner", "equipment": "none", "muscle": "胸/三头", "calories_per_set": 40},
        {"name": "波比跳", "difficulty": "intermediate", "equipment": "none", "muscle": "全身", "calories_per_set": 80},
        {"name": "硬拉", "difficulty": "advanced", "equipment": "barbell", "muscle": "背/腿", "calories_per_set": 60},
    ],
    "上肢": [
        {"name": "哑铃弯举", "difficulty": "beginner", "equipment": "dumbbell", "muscle": "二头", "calories_per_set": 30},
        {"name": "哑铃推举", "difficulty": "beginner", "equipment": "dumbbell", "muscle": "肩", "calories_per_set": 40},
        {"name": "引体向上", "difficulty": "intermediate", "equipment": "bar", "muscle": "背/二头", "calories_per_set": 50},
        {"name": "钻石俯卧撑", "difficulty": "intermediate", "equipment": "none", "muscle": "三头", "calories_per_set": 45},
    ],
    "下肢": [
        {"name": "弓步蹲", "difficulty": "beginner", "equipment": "none", "muscle": "腿/臀", "calories_per_set": 45},
        {"name": "臀桥", "difficulty": "beginner", "equipment": "none", "muscle": "臀", "calories_per_set": 35},
        {"name": "保加利亚深蹲", "difficulty": "intermediate", "equipment": "none", "muscle": "腿/臀", "calories_per_set": 55},
        {"name": "罗马尼亚硬拉", "difficulty": "intermediate", "equipment": "dumbbell", "muscle": "腿后侧/臀", "calories_per_set": 50},
    ],
    "核心": [
        {"name": "平板支撑", "difficulty": "beginner", "equipment": "none", "muscle": "核心", "calories_per_set": 20},
        {"name": "卷腹", "difficulty": "beginner", "equipment": "none", "muscle": "腹", "calories_per_set": 25},
        {"name": "俄罗斯转体", "difficulty": "beginner", "equipment": "none", "muscle": "腹斜肌", "calories_per_set": 30},
        {"name": "悬挂举腿", "difficulty": "advanced", "equipment": "bar", "muscle": "腹", "calories_per_set": 40},
    ],
    "有氧": [
        {"name": "快走", "difficulty": "beginner", "equipment": "none", "muscle": "全身", "calories_per_min": 5},
        {"name": "慢跑", "difficulty": "beginner", "equipment": "none", "muscle": "全身", "calories_per_min": 10},
        {"name": "跳绳", "difficulty": "intermediate", "equipment": "rope", "muscle": "全身", "calories_per_min": 13},
        {"name": "HIIT", "difficulty": "intermediate", "equipment": "none", "muscle": "全身", "calories_per_min": 15},
    ],
}


class ExercisePlanner:
    """运动计划生成器。"""

    def __init__(self, gateway=None):
        self.gateway = gateway

    def generate_plan(
        self,
        fitness_level: str = "beginner",
        available_days: int = 4,
        time_per_session: int = 45,
        equipment: str = "none",
        target_areas: str = "全身",
        goal: str = "减脂",
        user_id: str = "anonymous",
    ) -> dict:
        """生成运动计划。

        Args:
            fitness_level: 运动基础
            available_days: 每周可练天数
            time_per_session: 每次训练时长（分钟）
            equipment: 可用器械
            target_areas: 目标部位
            goal: 目标（减脂/增肌/塑形/体能）
            user_id: 用户ID
        Returns:
            包含周训练计划的字典
        """
        if self.gateway:
            plan = self._generate_with_llm(
                fitness_level, available_days, time_per_session,
                equipment, target_areas, goal, user_id,
            )
        else:
            plan = self._generate_with_rules(
                fitness_level, available_days, time_per_session,
                equipment, target_areas, goal,
            )
        return plan

    def _generate_with_llm(self, level, days, time_per, equip, areas, goal, user_id) -> dict:
        """使用大模型生成训练计划。"""
        prompt = f"""请为用户生成一周的运动训练计划。

用户信息：
- 运动基础：{level}
- 每周可练天数：{days}天
- 每次训练时长：{time_per}分钟
- 可用器械：{equip}
- 目标部位：{areas}
- 训练目标：{goal}

请以JSON格式输出：
{{
  "weekly_plan": [
    {{
      "day": 1,
      "day_name": "周一",
      "focus": "训练重点（如：下肢/上肢/有氧/休息）",
      "exercises": [
        {{
          "name": "动作名",
          "sets": 组数,
          "reps": "次数或时长",
          "rest": "休息时间",
          "notes": "注意事项"
        }}
      ],
      "estimated_calories": 估算消耗热量,
      "duration_min": 预计总时长
    }}
  ],
  "weekly_summary": {{
    "total_sessions": 训练次数,
    "total_estimated_calories": 周总消耗,
    "progression_note": "进阶建议"
  }}
}}

要求：
1. 动作难度匹配用户水平
2. 合理安排训练和休息日
3. 热身和拉伸时间包含在内
4. 给出明确的组数、次数和休息时间
"""
        try:
            response = self.gateway.complete(
                prompt, max_new_tokens=2048,
                user_id=user_id, scene="exercise_plan",
            )
            return self._parse_response(response)
        except Exception as exc:
            logger.warning("LLM训练计划生成失败: %s", exc)
            return self._generate_with_rules(level, days, time_per, equip, areas, goal)

    def _generate_with_rules(self, level, days, time_per, equip, areas, goal) -> dict:
        """规则引擎生成基础计划。"""
        difficulty_map = {"beginner": "beginner", "intermediate": "intermediate", "advanced": "advanced"}
        user_difficulty = difficulty_map.get(level, "beginner")

        # 目标部位拆分
        area_list = [a.strip() for a in areas.split("、,/") if a.strip()] if areas else ["全身"]
        if "全身" in area_list:
            area_list = ["全身", "上肢", "下肢", "核心", "有氧"]

        # 训练日安排
        day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekly_plan = []
        sessions = 0
        total_calories = 0

        for day_idx in range(7):
            day_name = day_names[day_idx]
            # 间隔安排训练日
            if day_idx < days * (7 // max(days, 1) + 1) and sessions < days and day_idx % 2 == 0:
                focus = area_list[sessions % len(area_list)]
                exercises = self._pick_exercises(focus, user_difficulty, equip, time_per)
                est_calories = sum(e.get("calories_per_set", 30) * e.get("sets", 3) for e in exercises)
                total_calories += est_calories
                sessions += 1
                weekly_plan.append({
                    "day": day_idx + 1,
                    "day_name": day_name,
                    "focus": focus,
                    "exercises": [
                        {
                            "name": e["name"],
                            "sets": 3,
                            "reps": "12-15次" if e.get("difficulty") == "beginner" else "8-12次",
                            "rest": "60秒" if e.get("difficulty") == "beginner" else "90秒",
                            "notes": f"目标肌群: {e.get('muscle', '')}",
                        }
                        for e in exercises
                    ],
                    "estimated_calories": est_calories,
                    "duration_min": time_per,
                })
            else:
                weekly_plan.append({
                    "day": day_idx + 1,
                    "day_name": day_name,
                    "focus": "休息",
                    "exercises": [],
                    "estimated_calories": 0,
                    "duration_min": 0,
                })

        return {
            "weekly_plan": weekly_plan,
            "weekly_summary": {
                "total_sessions": sessions,
                "total_estimated_calories": total_calories,
                "progression_note": f"建议每2周适当增加训练量或强度",
            },
            "source": "rule_engine",
        }

    def _pick_exercises(self, area: str, difficulty: str, equipment: str, time_limit: int) -> list:
        """从动作库中选择合适的动作。"""
        pool = EXERCISE_DATABASE.get(area, EXERCISE_DATABASE["全身"])
        # 按难度过滤
        difficulty_order = {"beginner": 0, "intermediate": 1, "advanced": 2}
        user_level = difficulty_order.get(difficulty, 0)

        filtered = [e for e in pool if difficulty_order.get(e["difficulty"], 0) <= user_level + 1]
        if not filtered:
            filtered = pool

        # 器械过滤
        if equipment == "none":
            no_equip = [e for e in filtered if e["equipment"] == "none"]
            if no_equip:
                filtered = no_equip

        # 根据时间限制选择动作数量
        exercise_count = min(len(filtered), max(3, time_limit // 10))
        return filtered[:exercise_count]

    @staticmethod
    def _parse_response(response: str) -> dict:
        """解析LLM返回的JSON。"""
        try:
            data = json.loads(response)
            data["source"] = "llm"
            return data
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{[\s\S]*\}', response)
            if match:
                try:
                    data = json.loads(match.group())
                    data["source"] = "llm"
                    return data
                except json.JSONDecodeError:
                    pass
        return {"weekly_plan": [], "source": "llm_raw", "raw_response": response[:500]}
