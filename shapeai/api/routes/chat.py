"""对话路由 — 对话发起（流式SSE / 异步轮询）、会话管理。"""

import json
import asyncio
import logging
import threading
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..models import ChatRequest, ChatResponse, SessionListResponse
from ..security import get_auth_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["对话"])


# ─────────────────────────────────────────────────────────────
#  异步轮询任务存储
# ─────────────────────────────────────────────────────────────
# task_id -> {"status", "result", "error", "session_id", "created_at", "user_id"}
# 用途：/chat/start 在后台线程跑 AgentLoop，前端用 /chat/poll 轮询结果，
# 避免长连接 SSE 在后端慢响应时被超时 abort。
_chat_tasks: dict = {}
_chat_tasks_lock = threading.Lock()
_TASK_TTL_SECONDS = 600  # 任务结果保留 10 分钟后清理


def _run_agent_task(task_id: str, agent, message: str) -> None:
    """后台线程：执行 agent._ask_continuing，完成后把结果写入任务存储。

    如果任务已被用户通过 /chat/cancel 终止（status=cancelled），
    则不覆盖取消状态，避免已被终止的结果又返回给前端。
    """
    try:
        response = agent._ask_continuing(message)
        with _chat_tasks_lock:
            task = _chat_tasks.get(task_id)
            if task and task.get("status") != "cancelled":
                task["status"] = "done"
                task["result"] = response
                task["session_id"] = agent.session.get("id", task.get("session_id", ""))
                task["finished_at"] = datetime.now().isoformat()
        logger.info("[chat_task] 完成 task_id=%s result_len=%d", task_id, len(response or ""))
    except Exception as exc:
        logger.exception("[chat_task] 失败 task_id=%s", task_id)
        with _chat_tasks_lock:
            task = _chat_tasks.get(task_id)
            if task:
                task["status"] = "error"
                task["error"] = str(exc)
                task["finished_at"] = datetime.now().isoformat()


def _cleanup_expired_tasks() -> None:
    """清理过期任务（lazy 清理，在 poll 时调用）。"""
    now = datetime.now()
    expired = []
    with _chat_tasks_lock:
        for tid, task in _chat_tasks.items():
            created = task.get("created_at")
            if created:
                try:
                    created_dt = datetime.fromisoformat(created)
                    if (now - created_dt).total_seconds() > _TASK_TTL_SECONDS:
                        expired.append(tid)
                except (ValueError, TypeError):
                    expired.append(tid)
            else:
                expired.append(tid)
        for tid in expired:
            task = _chat_tasks.pop(tid, None)
            # 释放 agent 引用，避免长期持有拖慢 GC
            if task:
                task.pop("agent", None)
    if expired:
        logger.debug("[chat_task] 清理过期任务 %d 个", len(expired))


@router.post("/send", summary="提交用户消息（立即入库）")
async def chat_send(request: ChatRequest, req: Request):
    """提交用户消息并立即写入会话历史。

    前端调用此接口后，用户消息已持久化到后端，
    返回 session_id 供后续 /stream 或 /ask 使用。
    即使用户刷新页面，提问也不会丢失。
    """
    app_state = req.app.state
    agent = app_state.create_agent(
        session_id=request.session_id,
        user_id=get_auth_user_id(req, request.user_id),
        user_profile=request.user_profile,
    )
    # 立即将用户消息写入会话历史（持久化）
    agent.record({"role": "user", "content": request.message})
    agent.memory.add_message("user", request.message)

    return {
        "session_id": agent.session["id"],
        "user_message": request.message,
        "message_count": len(agent.session.get("history", [])),
    }
@router.post("/ask", response_model=ChatResponse, summary="发起对话（非流式）")
async def chat_ask(request: ChatRequest, req: Request):
    """发起对话，返回完整回复。"""
    app_state = req.app.state
    agent = app_state.create_agent(
        session_id=request.session_id,
        user_id=get_auth_user_id(req, request.user_id),
        user_profile=request.user_profile,
    )
    # 如果用户消息还没入库（没有通过 /send 提交），先写入
    history = agent.session.get("history", [])
    if not history or history[-1].get("role") != "user" or history[-1].get("content") != request.message:
        agent.record({"role": "user", "content": request.message})
        agent.memory.add_message("user", request.message)

    # 运行 agent（跳过 agent_loop 中重复写入用户消息）
    response = agent.ask(request.message)
    return ChatResponse(
        session_id=agent.session["id"],
        response=response,
        user_id=get_auth_user_id(req, request.user_id),
    )


@router.post("/stream", summary="发起对话（流式SSE）")
async def chat_stream(request: ChatRequest, req: Request):
    """发起对话，以SSE流式返回。

    如果用户消息尚未入库（未通过 /send 提交），会在 agent.ask 中自动写入。
    如果已通过 /send 提交，agent.ask 中的 record 会追加一条重复的 user 消息，
    因此前端应优先调用 /send 再调用 /stream，且 /stream 不再重复传 message。
    """
    app_state = req.app.state
    agent = app_state.create_agent(
        session_id=request.session_id,
        user_id=get_auth_user_id(req, request.user_id),
        user_profile=request.user_profile,
    )

    # 检查用户消息是否已入库（通过 /send 提交过）
    history = agent.session.get("history", [])
    already_sent = (
        history
        and history[-1].get("role") == "user"
        and history[-1].get("content") == request.message
    )

    async def event_stream():
        # 如果已通过 /send 提交，用 _ask_without_duplicate 避免重复写入用户消息
        loop = asyncio.get_event_loop()
        if already_sent:
            response = await loop.run_in_executor(None, agent._ask_continuing, request.message)
        else:
            response = await loop.run_in_executor(None, agent.ask, request.message)

        # 逐字流式返回
        chunk_size = 2
        for i in range(0, len(response), chunk_size):
            chunk = response[i:i + chunk_size]
            yield f"data: {json.dumps({'token': chunk}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.02)

        yield f"data: {json.dumps({'done': True, 'session_id': agent.session['id']}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions", response_model=SessionListResponse, summary="查询会话列表")
async def list_sessions(req: Request, user_id: str = None):
    """查询会话列表。"""
    user_id = get_auth_user_id(req, user_id)
    sessions = req.app.state.session_store.list_sessions(user_id)
    return SessionListResponse(sessions=sessions)


@router.get("/today", summary="获取或创建当天会话")
async def get_today_session(req: Request, user_id: str = "anonymous"):
    """获取或创建当天的会话。

    如果今天已有会话，返回最近一个（含完整历史消息）；
    如果今天还没有会话，创建新会话并返回。
    前端刷新页面时调用此接口，可以恢复当天对话。
    """
    user_id = get_auth_user_id(req, user_id)
    session = req.app.state.session_store.get_or_create_today(user_id)
    return {
        "session_id": session["id"],
        "created_at": session.get("created_at", ""),
        "history": session.get("history", []),
        "message_count": len(session.get("history", [])),
    }


@router.get("/sessions/by-date", summary="按日期查询会话历史")
async def list_sessions_by_date(
    req: Request,
    user_id: str = "anonymous",
    date: str = None,
):
    """按日期查询会话历史（返回合并后的完整消息列表，与 /chat/today 格式一致）。

    Args:
        user_id: 用户ID（登录态优先，参数仅作未鉴权回退）
        date: 日期字符串 YYYY-MM-DD，不传默认今天
    """
    user_id = get_auth_user_id(req, user_id)
    session = req.app.state.session_store.get_by_date(user_id, date or "")
    return {
        "session_id": session["id"],
        "created_at": session.get("created_at", ""),
        "history": session.get("history", []),
        "message_count": len(session.get("history", [])),
    }


@router.get("/sessions/{session_id}", summary="查询会话历史")
async def get_session(session_id: str, req: Request):
    """查询指定会话的历史记录。"""
    try:
        session = req.app.state.session_store.load(session_id)
        return {"session_id": session_id, "history": session.get("history", [])}
    except FileNotFoundError:
        return {"error": "会话不存在"}


@router.delete("/sessions/{session_id}", summary="清空会话历史")
async def clear_session(session_id: str, req: Request):
    """清空指定会话的历史记录。"""
    try:
        session = req.app.state.session_store.clear_history(session_id)
        return {"session_id": session_id, "message": "会话历史已清空"}
    except FileNotFoundError:
        return {"error": "会话不存在"}


@router.delete("/sessions/{session_id}/delete", summary="删除会话")
async def delete_session(session_id: str, req: Request):
    """删除指定会话。"""
    deleted = req.app.state.session_store.delete(session_id)
    if deleted:
        return {"session_id": session_id, "message": "会话已删除"}
    return {"error": "会话不存在"}


# ─────────────────────────────────────────────────────────────
#  异步轮询接口（/chat/start + /chat/poll）
# ─────────────────────────────────────────────────────────────

@router.post("/start", summary="发起对话（异步，前端轮询 /chat/poll 取结果）")
async def chat_start(request: ChatRequest, req: Request):
    """发起对话，立即返回 task_id。

    后端在后台线程执行 AgentLoop，前端通过 GET /chat/poll?task_id=xxx 轮询结果。
    避免 SSE 长连接在后端慢响应（如模型降级耗时几十秒）时被超时 abort。
    """
    app_state = req.app.state
    agent = app_state.create_agent(
        session_id=request.session_id,
        user_id=get_auth_user_id(req, request.user_id),
        user_profile=request.user_profile,
    )
    # 立即将用户消息写入会话历史（持久化，刷新不丢失）
    agent.record({"role": "user", "content": request.message})
    agent.memory.add_message("user", request.message)

    task_id = str(uuid.uuid4())
    with _chat_tasks_lock:
        _chat_tasks[task_id] = {
            "status": "running",
            "result": "",
            "error": None,
            "session_id": agent.session["id"],
            "created_at": datetime.now().isoformat(),
            "finished_at": None,
            "user_id": request.user_id,
        }

    # 启动后台线程执行 AgentLoop（daemon=True，进程退出时自动结束）
    thread = threading.Thread(
        target=_run_agent_task,
        args=(task_id, agent, request.message),
        daemon=True,
        name=f"chat_task_{task_id[:8]}",
    )
    thread.start()

    # 在任务存储里登记 agent 引用，供 /chat/poll 与 /chat/extract 读取后台提取结果
    with _chat_tasks_lock:
        _chat_tasks[task_id]["agent"] = agent

    logger.info("[chat_task] 已启动 task_id=%s session_id=%s user=%s",
                task_id, agent.session["id"], request.user_id)

    return {
        "task_id": task_id,
        "session_id": agent.session["id"],
        "status": "running",
    }


@router.get("/poll", summary="轮询对话任务结果")
async def chat_poll(task_id: str, req: Request):
    """轮询 /chat/start 发起的对话任务状态。

    返回 {status, result, error, session_id, done, extract_status}：
    - status="running"：AgentLoop 仍在执行，继续轮询
    - status="done"：完成，result 为完整回复
    - status="error"：失败，error 为错误信息
    - extract_status="pending"：后台提取仍在进行（前端可用 /chat/extract 拉取）
    - extract_status="ready"：提取结果已就绪
    - extract_status="none"：无提取结果（主回复已返回且无饮食/饮水记录）
    """
    _cleanup_expired_tasks()

    with _chat_tasks_lock:
        task = _chat_tasks.get(task_id)
        if not task:
            return {"task_id": task_id, "status": "unknown", "done": True,
                    "error": "任务不存在或已过期", "result": "", "session_id": "",
                    "extract_status": "none"}
        agent = task.get("agent")
        # 后台提取状态：done 但 last_extract_result 为 None 说明提取线程还在跑
        if task["status"] == "done":
            extract_status = "ready" if (agent and getattr(agent, "last_extract_result", None) is not None) else "pending"
        else:
            extract_status = "none"
        # 返回快照（避免外部修改）
        return {
            "task_id": task_id,
            "status": task["status"],
            "result": task["result"] or "",
            "error": task["error"],
            "session_id": task.get("session_id", ""),
            "done": task["status"] in ("done", "error", "cancelled"),
            "extract_status": extract_status,
        }


@router.get("/extract", summary="拉取后台提取结果（饮食/饮水）")
async def chat_extract(task_id: str, req: Request):
    """拉取 /chat/start 任务的后台提取结果。

    主回复生成后立即返回（提取在后台线程执行），前端在用户阅读回复的
    同时轮询本接口拿提取结果，弹“确认记录”卡片。

    返回 {status, diet_data, water_data}：
    - status="ready"：提取完成，diet_data/water_data 可能为 None（无记录）
    - status="pending"：提取仍在进行，稍后再来
    - status="none"：任务不存在/未完成/无提取（终结态，前端停止轮询）
    """
    with _chat_tasks_lock:
        task = _chat_tasks.get(task_id)
        if not task:
            return {"status": "none", "diet_data": None, "water_data": None}
        agent = task.get("agent")
        task_status = task.get("status")

    # 主任务未完成时提取结果尚不可用
    if task_status != "done":
        return {"status": "none", "diet_data": None, "water_data": None}

    result = getattr(agent, "last_extract_result", None) if agent else None
    if result is None:
        return {"status": "pending", "diet_data": None, "water_data": None}

    diet_data = result.get("diet_data")
    water_data = result.get("water_data")
    # 提取结果只拉取一次，拉完即清（防止同一结果被重复弹卡片）
    with _chat_tasks_lock:
        t = _chat_tasks.get(task_id)
        if t and t.get("agent") is not None:
            t["agent"].last_extract_result = None
    return {
        "status": "ready",
        "diet_data": diet_data,
        "water_data": water_data,
    }


@router.post("/cancel", summary="终止正在生成的对话任务")
async def chat_cancel(task_id: str, req: Request):
    """终止 /chat/start 发起的对话任务。

    用户在前端点击"停止生成"时调用。将任务标记为 cancelled 后：
    - /chat/poll 会立即返回 status=cancelled（done=True），前端停止轮询；
    - 后台线程完成时不会覆盖取消状态，结果不再返回给前端。
    """
    with _chat_tasks_lock:
        task = _chat_tasks.get(task_id)
        if not task:
            return {"task_id": task_id, "success": False, "message": "任务不存在或已结束"}
        if task["status"] == "running":
            task["status"] = "cancelled"
            task["error"] = "用户已手动终止生成"
            task["finished_at"] = datetime.now().isoformat()
            logger.info("[chat_task] 已终止 task_id=%s", task_id)
            return {"task_id": task_id, "success": True, "message": "已终止生成"}
        return {"task_id": task_id, "success": False, "message": f"任务已结束（{task['status']}）"}
