"""API 层 — FastAPI 应用。

对外提供标准化API接口：
- 对话发起接口（流式SSE）
- 会话历史查询/清空接口
- 单工具手动调用接口
- 知识库管理接口
- 食物识别接口
- 模型网关状态查询接口
"""

from .app import create_app

__all__ = ["create_app"]
