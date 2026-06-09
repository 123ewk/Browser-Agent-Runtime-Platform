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
from app.infra.postgres import PostgresClient
from app.repository.task import TaskRepository
from app.repository.task_step import TaskStepRepository
from app.runtime.event_bus import EventBus
from app.runtime.policy_engine import PolicyEngine
from app.runtime.protocol.schemas import ActionDetail, Command, RuntimeEvent
from app.runtime.protocol.types import CommandType, EventType, TaskState
from app.runtime.task_runner import BrowserTaskRunner, TaskContext
from app.runtime.task_state import TaskStateManager
from app.runtime.trajectory import Trajectory
from app.runtime.ws_manager import WebSocketManager
from app.schema.task import TaskCreate

router = APIRouter(prefix="/tasks", tags=["tasks"])
log = structlog.get_logger(__name__)

# ── 全局单例(V1 简单做法,后续用 DI) ──
_event_bus = EventBus()
_task_state_mgr = TaskStateManager(_event_bus)
_ws_manager = WebSocketManager(_event_bus)
_policy_engine: PolicyEngine | None = None
_pg_client: PostgresClient | None = None
_timeline_recorder: object | None = None  # TimelineRecorder 实例(在 init 中赋值)
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


def init_timeline_recorder(pg: PostgresClient) -> None:
    """初始化 TimelineRecorder + 存储 pg client 引用 —— 在 lifespan startup 后调用"""
    from app.runtime.timeline_recorder import TimelineRecorder as TR

    global _pg_client, _timeline_recorder
    _pg_client = pg
    _timeline_recorder = TR(_event_bus, pg, _task_state_mgr)
    asyncio.create_task(_timeline_recorder.start())
    log.info("timeline_recorder.initialized")


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
    Response: {"task_id": "550e8400-e29b-...", "state": "running"}

    V1: 支持多任务并发,每个 task_id 独立的 BrowserTaskRunner。
    task_id 格式为 UUID,可直接用作 DB 外键。
    """
    # 生成 UUID task_id
    task_id = str(uuid4())

    # 写入 tasks 表(TimelineRecorder 需要 FK 引用)
    if _pg_client is not None:
        session = _pg_client.session()
        try:
            repo = TaskRepository(session)
            await repo.create(user_id, payload, task_id=UUID(task_id))
            await session.commit()
        except Exception:
            await session.rollback()
            log.warning("task.db_write_failed", task_id=task_id, exc_info=True)
        finally:
            await session.close()

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
        user_id=user_id,
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


@router.get("")
async def list_tasks(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    search: str | None = Query(None),
    user_id: UUID = Depends(get_current_user_id),
) -> dict:
    """分页查询任务列表 —— Task Center 表格 + Dashboard 最近任务

    数据源: tasks 表(TaskRepository.list_by_user)
    回退: 内存 _task_state_mgr + _active_runners(DB 不可用时)
    """
    if _pg_client is not None:
        session = _pg_client.session()
        try:
            repo = TaskRepository(session)
            result = await repo.list_by_user(
                user_id,
                status=status,
                limit=pageSize,
                offset=(page - 1) * pageSize,
            )
            await session.commit()
            return {
                "items": [
                    {
                        "id": str(t.id),
                        "goal": t.goal,
                        "agentName": "browser-agent",
                        "status": t.status,
                        "createdAt": t.created_at.isoformat(),
                        "updatedAt": t.updated_at.isoformat(),
                        "costUsd": 0,
                    }
                    for t in result.items
                ],
                "total": result.total,
                "page": page,
                "pageSize": pageSize,
            }
        except Exception:
            await session.rollback()
            log.warning("task.list_query_failed", exc_info=True)
        finally:
            await session.close()

    # 回退: 从内存返回(测试环境 / DB 不可用)
    items = []
    for tid, _runner in _active_runners.items():
        state = _task_state_mgr.get_state(tid)
        items.append(
            {
                "id": tid,
                "goal": "",
                "agentName": "browser-agent",
                "status": state.value,
                "createdAt": "",
                "updatedAt": "",
                "costUsd": 0,
            }
        )
    return {
        "items": items,
        "total": len(items),
        "page": page,
        "pageSize": pageSize,
    }


@router.get("/{task_id}/timeline")
async def get_task_timeline(
    task_id: str,
    user_id: UUID = Depends(get_current_user_id),
) -> list[dict]:
    """获取任务步骤时间线 —— 独立拉取(非 WS)

    数据源: task_steps 表(TaskStepRepository.list_by_task)
    鉴权: 校验 task 归属当前用户,非归属返回空列表。
    """
    if _pg_client is not None:
        try:
            task_uuid = UUID(task_id)
        except ValueError:
            return []

        session = _pg_client.session()
        try:
            # 校验任务归属
            task_repo = TaskRepository(session)
            task = await task_repo.get_by_id(task_uuid)
            if task is None or task.user_id != user_id:
                return []

            # 查询步骤
            step_repo = TaskStepRepository(session)
            steps = await step_repo.list_by_task(task_uuid)
            await session.commit()
            return [
                {
                    "id": str(s.id),
                    "index": s.step_index,
                    "kind": _step_kind_from_action(s.action),
                    "title": s.action,
                    "summary": (s.result or {}).get("summary", ""),
                    "startedAt": "",
                    "durationMs": (s.result or {}).get("duration_ms", 0) or 0,
                    "tokens": s.tokens_used or 0,
                }
                for s in steps
            ]
        except Exception:
            await session.rollback()
            log.warning("timeline.query_failed", task_id=task_id, exc_info=True)
        finally:
            await session.close()

    return []


def _step_kind_from_action(action: str) -> str:
    """将 Worker action 类型映射为前端 TimelineStepKind"""
    if action in ("navigate", "click", "input_text", "screenshot", "extract", "scroll"):
        return "tool"
    if action.startswith("ERROR") or action.startswith("STEP_FAILED"):
        return "observe"
    return "tool"


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
    """后台执行循环: STEP_COMPLETE → PolicyEngine.decide → CONTINUE, 直到终止

    终止条件(任一触发则发送 STOP):
    - PolicyEngine.decide() 返回 is_terminal=True
    - step_index >= max_steps
    - 连续 3 次相同动作(类型+目标一致, 防死循环)
    - 连续 3 次错误(不可恢复)
    - Worker TASK_FINISHED(正常/异常结束)
    - 总超时
    """
    MAX_CONSECUTIVE_ERRORS = 3
    MAX_SAME_ACTION = 3

    trajectory = Trajectory()
    consecutive_errors = 0
    last_action_type: str | None = None
    last_action_target: str | None = None
    same_action_count = 0
    result_state = TaskState.FAILED
    result_reason = ""
    # asyncio.Queue 保证并发安全: 多个 handler 同时 put 不会丢事件
    event_queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue()

    # 加载用户偏好(长期记忆) — 注入 PolicyEngine system prompt
    user_prefs: list | None = None
    if _pg_client is not None and context.user_id is not None:
        session = _pg_client.session()
        try:
            from app.repository.user_preference import UserPreferenceRepository

            pref_repo = UserPreferenceRepository(session)
            user_prefs = await pref_repo.list_by_user(context.user_id)
            log.info("preferences.loaded_for_task", task_id=task_id, count=len(user_prefs))
        except Exception:
            log.warning("preferences.load_failed", task_id=task_id, exc_info=True)
            # 加载失败不阻断任务,继续不带偏好执行
        finally:
            await session.close()

    def _new_cmd_id() -> str:
        return f"cmd-{uuid4().hex[:12]}"

    # ── 事件处理内联函数(必须 async,EventBus 类型签名要求) ──
    async def _on_step_complete(event: RuntimeEvent) -> None:
        if event.task_id == task_id:
            await event_queue.put(event)

    async def _on_error(event: RuntimeEvent) -> None:
        if event.task_id == task_id:
            await event_queue.put(event)

    async def _on_task_finished(event: RuntimeEvent) -> None:
        if event.task_id == task_id:
            await event_queue.put(event)

    # 先订阅再启动(防竞态)
    _event_bus.subscribe(EventType.STEP_COMPLETE, _on_step_complete)
    _event_bus.subscribe(EventType.ERROR, _on_error)
    _event_bus.subscribe(EventType.TASK_FINISHED, _on_task_finished)

    try:
        await runner.start_task(context)

        # ── 自动循环 ──
        while True:
            try:
                event = await asyncio.wait_for(
                    event_queue.get(),
                    timeout=context.timeout_seconds + 60,
                )
            except TimeoutError:
                log.error("task.timeout", task_id=task_id)
                result_state = TaskState.FAILED
                result_reason = "任务执行超时"
                await runner.send_command(
                    Command(
                        command_id=_new_cmd_id(),
                        type=CommandType.STOP,
                        payload={"reason": "timeout"},
                    )
                )
                break

            if event.event == EventType.STEP_COMPLETE:
                payload = event.payload
                step_index = payload.get("index", 0)
                consecutive_errors = 0

                # 追加 Trajectory(供 PolicyEngine 参考)
                trajectory.add_step(
                    action=ActionDetail(
                        type=payload.get("action", ""),
                        description=payload.get("summary", ""),
                    ),
                    url=payload.get("url"),
                    title=payload.get("title"),
                    summary=payload.get("summary", ""),
                )

                # 检查 max_steps 硬上限
                if step_index >= context.max_steps:
                    log.info("task.max_steps_reached", task_id=task_id, steps=step_index)
                    await runner.send_command(
                        Command(
                            command_id=_new_cmd_id(),
                            type=CommandType.STOP,
                            payload={"reason": "max_steps_reached"},
                        )
                    )
                    result_state = TaskState.COMPLETED
                    result_reason = f"达到最大步数 ({context.max_steps})"
                    break

                # PolicyEngine 决策下一步
                if _policy_engine is not None:
                    try:
                        decision = await _policy_engine.decide(
                            context.goal, trajectory, preferences=user_prefs
                        )

                        # 检查 is_terminal
                        if decision.is_terminal:
                            log.info("policy.is_terminal", task_id=task_id, step=step_index)
                            await runner.send_command(
                                Command(
                                    command_id=_new_cmd_id(),
                                    type=CommandType.STOP,
                                    payload={"reason": "is_terminal"},
                                )
                            )
                            result_state = TaskState.COMPLETED
                            result_reason = decision.reasoning
                            break

                        # 死循环检测: 连续相同动作
                        next_action = decision.action
                        if (
                            next_action.type == last_action_type
                            and next_action.target == last_action_target
                        ):
                            same_action_count += 1
                        else:
                            same_action_count = 1
                        last_action_type = next_action.type
                        last_action_target = next_action.target

                        if same_action_count >= MAX_SAME_ACTION:
                            log.warning(
                                "task.same_action_loop",
                                task_id=task_id,
                                action_type=next_action.type,
                                count=same_action_count,
                            )
                            await runner.send_command(
                                Command(
                                    command_id=_new_cmd_id(),
                                    type=CommandType.STOP,
                                    payload={"reason": "same_action_loop"},
                                )
                            )
                            result_state = TaskState.FAILED
                            result_reason = f"连续 {MAX_SAME_ACTION} 次相同动作,疑似死循环"
                            break

                        # 发送 CONTINUE(含下一步动作)
                        await runner.send_command(
                            Command(
                                command_id=_new_cmd_id(),
                                type=CommandType.CONTINUE,
                                payload={"action": next_action.model_dump()},
                            )
                        )
                        log.info(
                            "task.continue_loop",
                            task_id=task_id,
                            step=step_index,
                            next=next_action.type,
                        )

                    except Exception:
                        log.warning("policy_engine.decide_failed", task_id=task_id, exc_info=True)
                        result_state = TaskState.FAILED
                        result_reason = "PolicyEngine 决策失败"
                        await runner.send_command(
                            Command(
                                command_id=_new_cmd_id(),
                                type=CommandType.STOP,
                                payload={"reason": "policy_error"},
                            )
                        )
                        break

            elif event.event == EventType.ERROR:
                payload = event.payload
                consecutive_errors += 1
                log.warning(
                    "task.error_in_loop",
                    task_id=task_id,
                    error=payload.get("message", ""),
                    consecutive_errors=consecutive_errors,
                )

                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    result_state = TaskState.FAILED
                    result_reason = (
                        f"连续 {MAX_CONSECUTIVE_ERRORS} 次错误: {payload.get('message', 'unknown')}"
                    )
                    await runner.send_command(
                        Command(
                            command_id=_new_cmd_id(),
                            type=CommandType.STOP,
                            payload={"reason": "max_errors"},
                        )
                    )
                    break

                # 可重试: 发送空 CONTINUE,Worker 自行处理
                await runner.send_command(
                    Command(
                        command_id=_new_cmd_id(),
                        type=CommandType.CONTINUE,
                    )
                )

            elif event.event == EventType.TASK_FINISHED:
                payload = event.payload
                status = payload.get("status", "failed")
                if status == "completed":
                    result_state = TaskState.COMPLETED
                elif status == "cancelled":
                    # RUNNING → STOPPING → CANCELLED(合法路径)
                    # 直接 RUNNING→CANCELLED 不在转换表中,需经过 STOPPING
                    await _task_state_mgr.transition(task_id, TaskState.STOPPING, result_reason)
                    result_state = TaskState.CANCELLED
                else:
                    result_state = TaskState.FAILED
                result_reason = payload.get("summary", "")
                break

        # ── 循环结束, 状态转换 ──
        await _task_state_mgr.transition(task_id, result_state, result_reason)

    except Exception as e:
        log.exception("task.run_error", task_id=task_id)
        try:
            await _task_state_mgr.transition(task_id, TaskState.FAILED, str(e))
        except Exception:
            log.warning("task.state_transition_failed", task_id=task_id)
    finally:
        _event_bus.unsubscribe(EventType.STEP_COMPLETE, _on_step_complete)
        _event_bus.unsubscribe(EventType.ERROR, _on_error)
        _event_bus.unsubscribe(EventType.TASK_FINISHED, _on_task_finished)
        await runner.stop_task()
        _active_runners.pop(task_id, None)
