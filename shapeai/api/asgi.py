"""ASGI 入口 — 供 uvicorn 以导入字符串加载。

`shapeai serve --reload` 热重载模式下，uvicorn 要求传入 import string
（如 "shapeai.api.asgi:app"）而非 app 实例；直接传实例会被拒绝。
本模块只在被显式导入时才构建应用（含数据库连接、后台定时任务），
不影响其他模块对 shapeai.api 的普通导入。
"""

from .app import create_app

app = create_app()
