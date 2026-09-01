"""ShapeAI CLI 入口。

支持两种模式：
1. serve — 启动API服务
2. chat — 命令行对话模式（用于测试）
"""

import argparse
import sys
import json
import logging

from .config import API_HOST, API_PORT, __version__


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(
        prog="shapeai",
        description="ShapeAI 身材管理AI中台",
    )
    parser.add_argument("--version", action="version", version=f"ShapeAI {__version__}")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # serve 子命令
    serve_parser = subparsers.add_parser("serve", help="启动API服务")
    serve_parser.add_argument("--host", default=API_HOST, help="监听地址")
    serve_parser.add_argument("--port", type=int, default=API_PORT, help="监听端口")
    serve_parser.add_argument("--reload", action="store_true", help="开发模式热重载")

    # chat 子命令
    chat_parser = subparsers.add_parser("chat", help="命令行对话模式")
    chat_parser.add_argument("--user-id", default="cli-user", help="用户ID")
    chat_parser.add_argument("--session-id", default=None, help="恢复会话ID")

    # tool 子命令
    tool_parser = subparsers.add_parser("tool", help="直接调用工具")
    tool_parser.add_argument("tool_name", help="工具名称")
    tool_parser.add_argument("--args", default="{}", help="工具参数(JSON)")

    # init 子命令
    init_parser = subparsers.add_parser("init", help="初始化知识库")

    args = parser.parse_args(argv)

    if args.command == "serve":
        return _cmd_serve(args)
    elif args.command == "chat":
        return _cmd_chat(args)
    elif args.command == "tool":
        return _cmd_tool(args)
    elif args.command == "init":
        return _cmd_init()
    else:
        parser.print_help()
        return 0


def _cmd_serve(args) -> int:
    """启动API服务。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print(f"ShapeAI v{__version__} 启动中...")
    print(f"  监听: http://{args.host}:{args.port}")
    print(f"  文档: http://{args.host}:{args.port}/docs")

    try:
        import uvicorn

        if args.reload:
            # 热重载模式必须传 import string，传 app 实例会被 uvicorn 拒绝
            # （会话/模型等有状态对象在重载时会整体重建，更安全）。
            uvicorn.run(
                "shapeai.api.asgi:app",
                host=args.host,
                port=args.port,
                reload=True,
            )
        else:
            from .api import create_app

            app = create_app()
            uvicorn.run(app, host=args.host, port=args.port)
        return 0
    except ImportError:
        print("错误: 需要安装 uvicorn 才能启动API服务")
        print("  pip install uvicorn")
        return 1
    except KeyboardInterrupt:
        print("\n服务已停止")
        return 0


def _cmd_chat(args) -> int:
    """命令行对话模式。"""
    from .gateway import ModelGateway
    from .agent import SessionStore
    from .agent.runtime import ShapeAgent
    from .tools import ToolExecutor, build_tool_registry
    from .rag import KnowledgeBase
    from .safety import SafetyGuard

    logging.basicConfig(level=logging.WARNING)

    print(f"ShapeAI v{__version__} 对话模式 (输入 quit 退出)")
    print("-" * 50)

    gateway = ModelGateway()
    session_store = SessionStore()
    tool_executor = ToolExecutor(gateway)
    tools = build_tool_registry(tool_executor)
    kb = KnowledgeBase()
    kb.initialize()
    guard = SafetyGuard()

    if args.session_id:
        try:
            agent = ShapeAgent.from_session(
                gateway=gateway, session_store=session_store,
                session_id=args.session_id, tools=tools,
                tool_executor=tool_executor, rag_retriever=kb,
                safety_guard=guard, user_id=args.user_id,
            )
            print(f"已恢复会话: {args.session_id}")
        except FileNotFoundError:
            print(f"会话 {args.session_id} 不存在，创建新会话")
            agent = ShapeAgent(
                gateway=gateway, session_store=session_store,
                user_id=args.user_id, tools=tools,
                tool_executor=tool_executor, rag_retriever=kb,
                safety_guard=guard,
            )
    else:
        agent = ShapeAgent(
            gateway=gateway, session_store=session_store,
            user_id=args.user_id, tools=tools,
            tool_executor=tool_executor, rag_retriever=kb,
            safety_guard=guard,
        )

    print(f"会话ID: {agent.session['id']}")
    print("-" * 50)

    while True:
        try:
            user_input = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("再见！")
            break

        print("\nAI: ", end="", flush=True)
        response = agent.ask(user_input)
        print(response)

    return 0


def _cmd_tool(args) -> int:
    """直接调用工具。"""
    from .gateway import ModelGateway
    from .tools import ToolExecutor

    try:
        tool_args = json.loads(args.args)
    except json.JSONDecodeError as exc:
        print(f"参数JSON解析失败: {exc}")
        return 1

    gateway = ModelGateway()
    executor = ToolExecutor(gateway)
    result = executor.execute(args.tool_name, tool_args)
    print(result["content"])
    if result.get("metadata", {}).get("tool_status") != "ok":
        return 1
    return 0


def _cmd_init() -> int:
    """初始化知识库。"""
    from .rag import KnowledgeBase

    print("初始化知识库...")
    kb = KnowledgeBase()
    kb.initialize()
    stats = kb.get_stats()
    print(f"知识库初始化完成:")
    print(f"  文档块总数: {stats['total_documents']}")
    print(f"  词汇表大小: {stats['vocab_size']}")
    print(f"  分类: {stats['by_category']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
