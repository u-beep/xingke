"""模块4：多模态图像识别服务。

所有视觉类AI能力的统一出口，独立部署、独立扩缩容。
MVP版本实现食物图像识别（基于规则+LLM描述）。
"""

from .food_recognition import FoodRecognitionService

__all__ = ["FoodRecognitionService"]
