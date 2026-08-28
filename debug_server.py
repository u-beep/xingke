"""PyCharm 调试入口 — 启动 ShapeAI 完整 API 服务。

所有路由都会注册，在任意 routes/*.py 里打断点即可调试对应接口。

用法:
  1. PyCharm 中右键 -> Debug 'debug_server'
  2. 打开 http://localhost:8900/docs 用 Swagger UI 测试任意接口
  3. 或用下方 curl 命令触发对应接口

全部接口清单 (所有路径前缀 /api/v1):

  对话 (shapeai/api/routes/chat.py):
    POST   /chat/ask              非流式对话
    POST   /chat/stream           流式SSE对话
    GET    /chat/sessions         会话列表
    GET    /chat/sessions/{id}    查询会话历史
    DELETE /chat/sessions/{id}    清空会话历史
    DELETE /chat/sessions/{id}/delete  删除会话

  工具 (shapeai/api/routes/tools.py):
    GET    /tools/list            列出所有工具
    POST   /tools/call            直接调用工具
    POST   /tools/calculate/bmr   计算BMR
    POST   /tools/calculate/tdee  计算TDEE
    POST   /tools/calculate/bmi   计算BMI
    POST   /tools/diet-plan       生成饮食方案
    POST   /tools/exercise-plan   生成运动计划
    POST   /tools/analyze-body    分析身材数据

  知识库 (shapeai/api/routes/knowledge.py):
    GET    /knowledge/stats       知识库统计
    GET    /knowledge/categories  分类列表
    POST   /knowledge/search      知识检索
    POST   /knowledge/add         添加文档
    POST   /knowledge/add-batch   批量添加
    DELETE /knowledge/clear       清空知识库

  图像识别 (shapeai/api/routes/image.py):
    POST   /vision/food-recognition       食物识别
    GET    /vision/food-database           食物数据库
    GET    /vision/low-confidence-log      低置信度记录

  系统 (shapeai/api/app.py):
    GET    /health               健康检查
    GET    /api/v1/gateway/stats  网关状态
    GET    /api/v1/safety/stats   安全统计
    GET    /api/v1/safety/log     安全日志
"""

import logging

from shapeai.api import create_app
from shapeai.config import API_HOST, API_PORT

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = create_app()


if __name__ == "__main__":
    import uvicorn

    print()
    print("=" * 60)
    print("  ShapeAI 调试服务")
    print("=" * 60)
    print(f"  服务地址: http://{API_HOST}:{API_PORT}")
    print(f"  Swagger: http://{API_HOST}:{API_PORT}/docs  <-- 推荐用这个测试接口")
    print(f"  断点设置: 在 shapeai/api/routes/ 下任意 .py 文件里打断点")
    print("=" * 60)
    print()
    uvicorn.run(app, host=API_HOST, port=API_PORT)
