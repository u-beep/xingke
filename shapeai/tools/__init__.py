"""模块2：身材管理领域工具引擎。

封装身材管理垂直场景的专属计算与生成能力，
既是Agent可调用的内置工具集，也支持业务侧直接API调用。
"""

from .calculator import (
    calculate_bmr, calculate_tdee, calculate_bmi,
    calculate_calorie_deficit, calculate_macros,
)
from .diet_planner import DietPlanner
from .exercise_planner import ExercisePlanner
from .body_analyzer import BodyAnalyzer
from .intervention import InterventionEngine
from .executor import ToolExecutor, build_tool_registry

__all__ = [
    "BodyAnalyzer",
    "DietPlanner",
    "ExercisePlanner",
    "InterventionEngine",
    "ToolExecutor",
    "build_tool_registry",
    "calculate_bmr",
    "calculate_bmi",
    "calculate_calorie_deficit",
    "calculate_macros",
    "calculate_tdee",
]
