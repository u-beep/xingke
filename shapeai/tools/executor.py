"""工具执行器 — 所有工具调用的总闸口。

在执行前串起安全与可控设计：
工具是否存在、参数是否合法、执行结果是否裁剪。
"""

import json
import logging
from functools import partial

from .calculator import calculate_bmr, calculate_tdee, calculate_bmi, calculate_calorie_deficit, calculate_macros
from .diet_planner import DietPlanner
from .exercise_planner import ExercisePlanner
from .body_analyzer import BodyAnalyzer
from .intervention import InterventionEngine

logger = logging.getLogger(__name__)

# ─── 工具规格定义 ───
TOOL_SPECS = {
    "calculate_bmr": {
        "schema": {"gender": "str", "age": "int", "weight": "float", "height": "float"},
        "risky": False,
        "description": "计算基础代谢率(BMR)，需要性别、年龄、体重、身高",
    },
    "calculate_tdee": {
        "schema": {"bmr": "float", "activity_level": "str='moderate'"},
        "risky": False,
        "description": "计算每日总能量消耗(TDEE)，需要BMR和活动水平",
    },
    "calculate_bmi": {
        "schema": {"weight": "float", "height": "float"},
        "risky": False,
        "description": "计算身体质量指数(BMI)和分类",
    },
    "calculate_macros": {
        "schema": {"target_calories": "float", "protein_ratio": "float=0.3", "carb_ratio": "float=0.4", "fat_ratio": "float=0.3"},
        "risky": False,
        "description": "计算宏量营养素(蛋白/碳水/脂肪)配比",
    },
    "generate_diet_plan": {
        "schema": {"gender": "str='male'", "age": "int=25", "weight": "float=70", "height": "float=175",
                   "activity_level": "str='moderate'", "target_deficit": "float=500",
                   "meals_per_day": "int=3", "preferences": "str=''", "allergies": "str=''", "days": "int=1"},
        "risky": False,
        "description": "生成个性化饮食方案，包含BMR/TDEE计算和食谱推荐",
    },
    "generate_exercise_plan": {
        "schema": {"fitness_level": "str='beginner'", "available_days": "int=4",
                   "time_per_session": "int=45", "equipment": "str='none'",
                   "target_areas": "str='全身'", "goal": "str='减脂'"},
        "risky": False,
        "description": "生成一周运动训练计划",
    },
    "analyze_body_data": {
        "schema": {"weight_records": "list=[]", "body_fat_records": "list=[]",
                   "goal": "str='减脂'", "target_weight": "float=0"},
        "risky": False,
        "description": "分析体重/体脂趋势，识别平台期，评估风险",
    },
    "generate_intervention": {
        "schema": {"scenario": "str", "context": "dict={}"},
        "risky": False,
        "description": "生成异常干预策略（连续超标/未打卡/体重波动/平台期/极端行为）",
    },
}


def _run_calculate_bmr(args):
    return json.dumps(calculate_bmr(
        gender=args.get("gender", "male"),
        age=int(args.get("age", 25)),
        weight=float(args.get("weight", 70)),
        height=float(args.get("height", 175)),
    ), ensure_ascii=False)


def _run_calculate_tdee(args):
    return json.dumps(calculate_tdee(
        bmr=float(args.get("bmr", 1500)),
        activity_level=args.get("activity_level", "moderate"),
    ), ensure_ascii=False)


def _run_calculate_bmi(args):
    return json.dumps(calculate_bmi(
        weight=float(args.get("weight", 70)),
        height=float(args.get("height", 175)),
    ), ensure_ascii=False)


def _run_calculate_macros(args):
    return json.dumps(calculate_macros(
        target_calories=float(args.get("target_calories", 1800)),
        protein_ratio=float(args.get("protein_ratio", 0.3)),
        carb_ratio=float(args.get("carb_ratio", 0.4)),
        fat_ratio=float(args.get("fat_ratio", 0.3)),
    ), ensure_ascii=False)


class ToolExecutor:
    """工具执行器。

    所有工具调用都经过这里，在执行前做参数校验和结果裁剪。
    """

    def __init__(self, gateway=None):
        """初始化工具执行器。

        Args:
            gateway: 模型网关实例，传给需要LLM的工具
        """
        self.gateway = gateway
        self.diet_planner = DietPlanner(gateway)
        self.exercise_planner = ExercisePlanner(gateway)
        self.body_analyzer = BodyAnalyzer(gateway)
        self.intervention_engine = InterventionEngine(gateway)
        self._max_output = 4000

    def execute(self, name: str, args: dict) -> dict:
        """执行一次工具调用。

        Args:
            name: 工具名称
            args: 工具参数字典
        Returns:
            {"content": str, "metadata": dict}
        """
        args = args or {}

        # 检查工具是否存在
        if name not in TOOL_SPECS:
            return {
                "content": f"error: 未知工具 '{name}'",
                "metadata": {"tool_status": "rejected", "error_code": "unknown_tool"},
            }

        # 参数校验
        spec = TOOL_SPECS[name]
        schema = spec["schema"]
        required = [k for k, v in schema.items() if "=" not in v and v != "list=[]" and v != "dict={}"]
        for req in required:
            if req not in args:
                return {
                    "content": f"error: 缺少必选参数 '{req}'",
                    "metadata": {"tool_status": "rejected", "error_code": "missing_argument"},
                }

        # 执行
        try:
            result = self._dispatch(name, args)
            content = str(result)
            if len(content) > self._max_output:
                content = content[:self._max_output] + f"\n...[truncated {len(content) - self._max_output} chars]"
            return {
                "content": content,
                "metadata": {"tool_status": "ok", "tool_name": name},
            }
        except Exception as exc:
            logger.error("工具执行失败 %s: %s", name, exc)
            return {
                "content": f"error: 工具 '{name}' 执行失败: {exc}",
                "metadata": {"tool_status": "error", "error_code": "tool_failed", "error_message": str(exc)},
            }

    def _dispatch(self, name: str, args: dict) -> str:
        """分发工具调用到对应执行函数。"""
        if name == "calculate_bmr":
            return _run_calculate_bmr(args)
        elif name == "calculate_tdee":
            return _run_calculate_tdee(args)
        elif name == "calculate_bmi":
            return _run_calculate_bmi(args)
        elif name == "calculate_macros":
            return _run_calculate_macros(args)
        elif name == "generate_diet_plan":
            result = self.diet_planner.generate_plan(
                gender=args.get("gender", "male"),
                age=int(args.get("age", 25)),
                weight=float(args.get("weight", 70)),
                height=float(args.get("height", 175)),
                activity_level=args.get("activity_level", "moderate"),
                target_deficit=float(args.get("target_deficit", 500)),
                meals_per_day=int(args.get("meals_per_day", 3)),
                preferences=args.get("preferences", ""),
                allergies=args.get("allergies", ""),
                cooking_equipment=args.get("cooking_equipment", ""),
                days=int(args.get("days", 1)),
            )
            return json.dumps(result, ensure_ascii=False)
        elif name == "generate_exercise_plan":
            result = self.exercise_planner.generate_plan(
                fitness_level=args.get("fitness_level", "beginner"),
                available_days=int(args.get("available_days", 4)),
                time_per_session=int(args.get("time_per_session", 45)),
                equipment=args.get("equipment", "none"),
                target_areas=args.get("target_areas", "全身"),
                goal=args.get("goal", "减脂"),
            )
            return json.dumps(result, ensure_ascii=False)
        elif name == "analyze_body_data":
            result = self.body_analyzer.analyze(
                weight_records=args.get("weight_records", []),
                body_fat_records=args.get("body_fat_records", []),
                goal=args.get("goal", "减脂"),
                target_weight=float(args.get("target_weight", 0)) or None,
            )
            return json.dumps(result, ensure_ascii=False)
        elif name == "generate_intervention":
            result = self.intervention_engine.generate_intervention(
                scenario=args.get("scenario", ""),
                context=args.get("context", {}),
            )
            return json.dumps(result, ensure_ascii=False)
        else:
            raise ValueError(f"未实现工具: {name}")


def build_tool_registry(executor: ToolExecutor) -> dict:
    """构建工具注册表，供 agent prompt 使用。

    Args:
        executor: 工具执行器
    Returns:
        {name: {schema, risky, description, run}} 工具注册表
    """
    registry = {}
    for name, spec in TOOL_SPECS.items():
        registry[name] = {
            **spec,
            "run": partial(executor.execute, name),
        }
    return registry
