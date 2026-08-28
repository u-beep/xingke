"""模块5：大模型网关与模型管理层。

统一封装所有底层大模型接入，向上提供标准化调用能力，
实现多模型路由、故障降级、成本管控。
"""

from .clients import FakeModelClient, ModelClient, OpenAICompatibleClient
from .gateway import ModelGateway
from .cost_tracker import CostTracker

__all__ = [
    "CostTracker",
    "FakeModelClient",
    "ModelClient",
    "ModelGateway",
    "OpenAICompatibleClient",
]
