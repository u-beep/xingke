"""对话路由 — 对话发起（流式SSE / 异步轮询）、会话管理。"""

import base64
import json
import asyncio
import logging
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from ..models import ChatRequest, ChatResponse, SessionListResponse
from ..security import get_auth_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["对话"])


class PendingEntryDecisionRequest(BaseModel):
    """确认或忽略会话中待录入的饮食/饮水提取结果。"""

    session_id: str = Field(..., min_length=1)
    pending_entry_id: str = Field(..., min_length=1)
    entry_type: str = Field(..., pattern="^(diet|water)$")
    status: str = Field(..., pattern="^(confirmed|dismissed)$")


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


class AppendMessageItem(BaseModel):
    """追加的单条消息。"""
    role: str = Field(..., pattern="^(user|assistant)$", description="消息角色")
    content: str = Field(..., description="消息内容")
    args: Optional[dict] = Field(None, description="附加数据（如 pending_entry 确认卡）")
    image_key: Optional[str] = Field(None, description="聊天图片对象 key（MinIO），用于刷新后还原图片预览")


class AppendMessagesRequest(BaseModel):
    """前端本地流程（拍照识别等）产生的对话持久化请求。"""
    user_id: Optional[str] = Field(None, description="用户ID，未传则取 X-User-Id 头")
    session_id: Optional[str] = Field(None, description="会话ID，为空时复用/新建当天会话")
    messages: list[AppendMessageItem] = Field(..., min_length=1, max_length=20, description="要追加的消息列表")


@router.post("/append-messages", summary="追加消息到会话（拍照识别等本地流程持久化）")
async def append_messages(request: AppendMessagesRequest, req: Request):
    """把前端本地生成（未走 agent 对话链路）的消息写入会话历史并持久化。

    典型场景：拍照识别饮食。该流程不经过 /chat/send 与 agent 回复，
    若不入库则刷新页面后对话消失。args 可携带 pending_entry，
    使确认卡在刷新后仍能还原。
    """
    app_state = req.app.state
    agent = app_state.create_agent(
        session_id=request.session_id,
        user_id=get_auth_user_id(req, request.user_id),
    )
    for item in request.messages:
        entry: dict = {"role": item.role, "content": item.content}
        args = dict(item.args) if item.args else {}
        if item.image_key:
            # 只接受本用户 chat/ 前缀下的对象，防止越权引用他人图片
            if item.image_key.startswith(f"chat/{get_auth_user_id(req)}/"):
                args["image_url"] = f"/api/v1/chat/images/{item.image_key}"
        if args:
            entry["args"] = args
        agent.record(entry)
        agent.memory.add_message(item.role, item.content)

    return {
        "success": True,
        "session_id": agent.session["id"],
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


class ChatImageUploadRequest(BaseModel):
    """聊天图片上传请求。"""
    image_base64: str = Field(..., min_length=32, description="Base64 编码图片（可含 data: 前缀）")


@router.post("/upload-image", summary="上传聊天图片（拍照识图预览持久化）")
async def upload_chat_image(request: ChatImageUploadRequest, req: Request):
    """把识图用的预览图片存入 MinIO，返回对象 key 与访问 URL。

    刷新后会话历史中的图片预览通过该 URL 还原，不再丢失。
    """
    user_id = get_auth_user_id(req)
    data_url = request.image_base64
    raw = data_url.split(",", 1)[-1]
    try:
        data = base64.b64decode(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="图片 base64 无效")
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片超过 8MB 限制")
    ctype = "image/png" if "image/png" in data_url[:64] else "image/jpeg"
    ext = "png" if ctype == "image/png" else "jpg"
    key = f"chat/{user_id}/{uuid.uuid4().hex}.{ext}"
    try:
        from ...storage import ensure_bucket, upload_bytes
        ensure_bucket()
        upload_bytes(key, data, ctype)
    except Exception as exc:
        logger.error("聊天图片上传失败: %s", exc)
        raise HTTPException(status_code=500, detail="图片上传失败，请稍后重试")
    return {"image_key": key, "image_url": f"/api/v1/chat/images/{key}"}


@router.get("/images/{object_key:path}", summary="获取聊天图片")
async def get_chat_image(object_key: str, req: Request):
    """读取 MinIO 中的聊天图片（<img> 标签可用 ?token= 查询参数鉴权）。"""
    user_id = get_auth_user_id(req)
    if not object_key.startswith(f"chat/{user_id}/"):
        raise HTTPException(status_code=403, detail="无权访问该图片")
    try:
        from ...storage import get_object_bytes
        data, ctype = get_object_bytes(object_key)
    except Exception:
        raise HTTPException(status_code=404, detail="图片不存在")
    return Response(
        content=data,
        media_type=ctype,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.delete("/sessions/by-date", summary="清空某天所有会话历史")
async def clear_sessions_by_date(
    req: Request,
    user_id: str = "anonymous",
    date: str = None,
):
    """清空指定日期的所有会话历史（当天可能存在多个会话，需全部清空）。

    Args:
        user_id: 用户ID（登录态优先，参数仅作未鉴权回退）
        date: 日期字符串 YYYY-MM-DD，不传默认今天
    """
    user_id = get_auth_user_id(req, user_id)
    cleared_ids = req.app.state.session_store.clear_by_date(user_id, date or None)
    # 同步丢弃内存中的 agent 缓存，避免旧实例把清空前的历史写回
    for sid in cleared_ids:
        req.app.state.invalidate_agent(sid)
    return {"cleared": cleared_ids, "count": len(cleared_ids), "message": f"已清空 {len(cleared_ids)} 个会话的历史"}


@router.delete("/sessions/{session_id}", summary="清空会话历史")
async def clear_session(session_id: str, req: Request):
    """清空指定会话的历史记录。"""
    try:
        session = req.app.state.session_store.clear_history(session_id)
        # 同步丢弃内存中的 agent 缓存，避免旧实例把清空前的历史写回
        req.app.state.invalidate_agent(session_id)
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
        "pending_entry_id": result.get("pending_entry_id"),
        "diet_data": diet_data,
        "water_data": water_data,
    }


@router.post("/pending-entry/resolve", summary="更新待确认饮食或饮水录入状态")
async def resolve_pending_entry(request: PendingEntryDecisionRequest, req: Request):
    """把确认/忽略结果持久化到对应 AI 消息，确保刷新后不会重复出现卡片。"""
    user_id = get_auth_user_id(req)
    store = req.app.state.session_store
    try:
        session = store.load(request.session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在")

    if session.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="无权操作该会话")

    status_key = f"{request.entry_type}_status"
    for message in reversed(session.get("history", [])):
        if message.get("role") != "assistant":
            continue
        args = message.get("args") or {}
        pending_entry = args.get("pending_entry") or {}
        if pending_entry.get("id") != request.pending_entry_id:
            continue
        pending_entry[status_key] = request.status
        args["pending_entry"] = pending_entry
        message["args"] = args
        store.save(session)
        return {"success": True, "status": request.status}

    raise HTTPException(status_code=404, detail="待确认录入不存在")


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
