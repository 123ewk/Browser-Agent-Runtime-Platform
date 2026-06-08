"""任务 API —— 创建任务 + WebSocket 事件流 + 状态查询

V1 只做最简接口:
  POST /tasks          — 创建任务(goal 文本),返回 task_id
  GET  /tasks/{id}     — 查询任务状态
  WS   /tasks/{id}/ws  — WebSocket 事件流
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.core.deps import get_current_user_id
from app.core.security import decode_token
from app.infra.llm import ChatLLM
from app.runtime.event_bus import EventBus
from app.runtime.policy_engine import PolicyEngine
from app.runtime.protocol.schemas import RuntimeEvent
from app.runtime.protocol.types import EventType, TaskState
from app.runtime.task_runner import BrowserTaskRunner, TaskContext
from app.runtime.task_state import TaskStateManager
from app.runtime.ws_manager import WebSocketManager
from app.schema.task import TaskCreate

router = APIRouter(prefix="/tasks", tags=["tasks"])
log = structlog.get_logger(__name__)

# ── 全局单例(V1 简单做法,后续用 DI) ──
_event_bus = EventBus()
_task_state_mgr = TaskStateManager(_event_bus)
_ws_manager = WebSocketManager(_event_bus)
_policy_engine: PolicyEngine | None = None
# 活跃的 runner 字典 —— 按 task_id 索引,支持多任务并发(M6 修复)
# V1 简单 in-memory 存储,进程重启会丢;V2 引入持久化或 Redis 存储
_active_runners: dict[str, BrowserTaskRunner] = {}


def init_policy_engine(llm_provider: ChatLLM) -> None:
    """初始化 PolicyEngine —— 在 FastAPI startup 后调用

    必须在 lifespan startup 完成后调用,因为需要 app.state.deps.llm。
    """
    global _policy_engine
    _policy_engine = PolicyEngine(llm_provider)
    log.info("policy_engine.initialized")


def get_event_bus() -> EventBus:
    return _event_bus


def get_task_state_manager() -> TaskStateManager:
    return _task_state_mgr


def get_ws_manager() -> WebSocketManager:
    return _ws_manager


# ═══════════════════════════════════════════════════════════════
# REST 端点
# ═══════════════════════════════════════════════════════════════


@router.post("")
async def create_task(
    payload: TaskCreate,
    user_id: UUID = Depends(get_current_user_id),
) -> dict:
    """创建并启动一个浏览器任务

    Request: {"goal": "打开百度搜索Python"}
    Response: {"task_id": "task-xxx", "state": "running"}

    V1: 支持多任务并发,每个 task_id 独立的 BrowserTaskRunner。
    """
    # 状态: PENDING → RUNNING
    task_id = f"task-{uuid4().hex[:12]}"

    # PolicyEngine: 决定第一个 action
    skill = "browser"
    action_dict = None
    if _policy_engine is not None:
        try:
            decision = await _policy_engine.decide(payload.goal)
            skill = decision.skill
            action_dict = decision.action.model_dump()
            log.info(
                "policy_engine.decided",
                task_id=task_id,
                action_type=decision.action.type,
                reasoning=decision.reasoning[:80],
            )
        except Exception:
            log.warning("policy_engine.decide_failed", task_id=task_id, exc_info=True)
            # 继续执行:Worker 有 _fallback_decide 兜底

    await _task_state_mgr.transition(task_id, TaskState.RUNNING, f"开始执行: {payload.goal}")

    # 启动 Worker —— 多任务并发:每个 task_id 独立 runner,登记到字典
    runner = BrowserTaskRunner(_event_bus)
    _active_runners[task_id] = runner

    context = TaskContext(
        task_id=task_id,
        goal=payload.goal,
        skill=skill,
        action=action_dict,
    )

    # 后台启动(不阻塞请求响应)
    # create_task 返回 Task 对象,异常不会传播到此处
    # _run_task 内部已有完整的异常处理 + 状态转换,无需外层 try/except
    task = asyncio.create_task(_run_task(runner, context, task_id))

    # 兜底: 如果 _run_task 内部异常处理有遗漏,记录到日志
    def _on_task_exception(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            log.exception("task.unhandled_exception", task_id=task_id, exc_info=exc)

    task.add_done_callback(_on_task_exception)

    log.info("task.created", task_id=task_id, goal=payload.goal)
    return {"task_id": task_id, "state": "running"}


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    user_id: UUID = Depends(get_current_user_id),
) -> dict:
    """查询任务状态"""
    state = _task_state_mgr.get_state(task_id)
    reason = _task_state_mgr.get_reason(task_id)
    return {
        "task_id": task_id,
        "state": state.value,
        "reason": reason,
    }


# ═══════════════════════════════════════════════════════════════
# WebSocket 端点
# ═══════════════════════════════════════════════════════════════


@router.websocket("/{task_id}/ws")
async def task_websocket(
    websocket: WebSocket,
    task_id: str,
    token: str = Query(...),
) -> None:
    """WebSocket 事件流 —— 前端 Timeline 的数据源

    客户端连接后持续接收 RuntimeEvent JSON,直到任务结束或连接断开。
    认证通过 query param ?token=xxx 传递(浏览器 WebSocket 不支持自定义请求头)。
    """
    # WS 层认证:验证 JWT token,失败关闭连接
    if decode_token(token) is None:
        await websocket.accept()
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await _ws_manager.connect(websocket, task_id=task_id)

    try:
        # 保持连接直到客户端断开
        while True:
            # 接收客户端消息(心跳/ping),虽 V1 不处理但需消费防止缓冲区满
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
            except TimeoutError:
                # 超时无消息是正常的,发送心跳保持连接
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break
            except WebSocketDisconnect:
                break
    except Exception:
        log.warning("ws.unexpected_error", task_id=task_id)
    finally:
        _ws_manager.disconnect(websocket, task_id=task_id)


# ═══════════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════════


async def _run_task(
    runner: BrowserTaskRunner,
    context: TaskContext,
    task_id: str,
) -> None:
    """后台执行任务,监听 TASK_FINISHED 后更新状态

    设计要点:
    - 必须在 runner.start_task() 之前订阅 TASK_FINISHED,
      否则 Worker 在订阅前完成会导致事件丢失(竞态条件)。
    """
    finished = asyncio.Event()
    result_state = TaskState.FAILED
    result_reason = ""

    async def on_task_finished(event: RuntimeEvent) -> None:
        nonlocal result_state, result_reason
        # 只处理当前 task 的事件,避免多任务并发时误触发
        if event.task_id != task_id:
            return
        payload = event.payload
        status = payload.get("status", "failed")
        if status == "completed":
            result_state = TaskState.COMPLETED
        elif status == "cancelled":
            result_state = TaskState.CANCELLED
        else:
            result_state = TaskState.FAILED
        result_reason = payload.get("summary", "")
        finished.set()

    # 先订阅再启动,避免竞态
    _event_bus.subscribe(EventType.TASK_FINISHED, on_task_finished)

    try:
        await runner.start_task(context)

        try:
            await asyncio.wait_for(finished.wait(), timeout=context.timeout_seconds + 30)
        except TimeoutError:
            result_state = TaskState.FAILED
            result_reason = "任务超时"
        finally:
            _event_bus.unsubscribe(EventType.TASK_FINISHED, on_task_finished)

        await _task_state_mgr.transition(task_id, result_state, result_reason)

    except Exception as e:
        log.exception("task.run_failed", task_id=task_id)
        try:
            await _task_state_mgr.transition(task_id, TaskState.FAILED, str(e))
        except Exception:
            log.warning("task.state_transition_failed_after_run_error", task_id=task_id)
    finally:
        # 任务完成后从字典中移除本任务的 runner 引用,避免内存泄漏
        # 仅当字典里的 runner 就是当前 runner 时才删除(避免误删后启动的同 task_id 新 runner)
        _active_runners.pop(task_id, None)
