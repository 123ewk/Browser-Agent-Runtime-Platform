"""任务 API —— 创建任务 + WebSocket 事件流 + 状态查询 + 任务控制

V1 接口:
  POST /tasks                  — 创建任务(goal 文本),返回 task_id
  GET  /tasks/{id}             — 查询任务状态
  GET  /tasks/{id}/timeline    — 查询任务时间轴
  POST /tasks/{id}/messages    — 发送人工确认/反馈(CONTINUE/REJECT)
  POST /tasks/{id}/stop        — 停止任务(CANCELLED)
  POST /tasks/{id}/pause       — 暂停任务(PAUSED,V1 Worker 退出, V2 支持续跑)
  POST /tasks/{id}/resume      — 继续任务(RUNNING,V1 仅状态恢复)
  WS   /tasks/{id}/ws          — WebSocket 事件流
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_id
from app.core.security import decode_token
from app.infra.llm import ChatLLM
from app.infra.postgres import PostgresClient
from app.repository.task import TaskRepository
from app.repository.task_step import TaskStepRepository
from app.runtime.checkpoint_manager import CheckpointManager
from app.runtime.event_bus import EventBus
from app.runtime.policy_engine import PolicyEngine
from app.runtime.protocol.constants import WAITING_USER_TIMEOUT
from app.runtime.protocol.schemas import (
    ActionDetail,
    Command,
    InterruptPayload,
    ResumePayload,
    RuntimeEvent,
)
from app.runtime.protocol.types import CommandType, EventType, ReActDecisionType, TaskState
from app.runtime.react_engine import ObservationState, ReActEngine
from app.runtime.task_runner import BrowserTaskRunner, TaskContext
from app.runtime.task_state import TaskStateManager
from app.runtime.trajectory import Trajectory
from app.runtime.watchdog import ProcessWatchdog
from app.runtime.ws_manager import WebSocketManager
from app.schema.checkpoint import FullCheckpointState
from app.schema.task import (
    TaskActionResponse,
    TaskCreate,
    TaskMessageCreate,
    TaskMessageOut,
    TaskOut,
    TaskUpdate,
)
from app.schema.task_step import TaskStepOut

router = APIRouter(prefix="/tasks", tags=["tasks"])
log = structlog.get_logger(__name__)

# ── 全局单例(V1 简单做法,后续用 DI) ──
_event_bus = EventBus()
_task_state_mgr = TaskStateManager(_event_bus)
_ws_manager = WebSocketManager(_event_bus)
_policy_engine: PolicyEngine | None = None
_react_engine: ReActEngine | None = None  # V2.5: 默认决策引擎
_pg_client: PostgresClient | None = None
_timeline_recorder: object | None = None  # TimelineRecorder 实例(在 init 中赋值)
_checkpoint_manager: CheckpointManager | None = None  # CheckpointManager 实例
_watchdog: ProcessWatchdog | None = None  # ProcessWatchdog 实例
# 活跃的 runner 字典 —— 按 task_id 索引,支持多任务并发(M6 修复)
# V1 简单 in-memory 存储,进程重启会丢;V2 引入持久化或 Redis 存储
_active_runners: dict[str, BrowserTaskRunner] = {}

# status 字段白名单 —— 用于 list_tasks 读路径的防御性过滤
# 与 app/runtime/protocol/types.py TaskState 枚举 + alembic 迁移 4f8a2c1b3d5e CHECK 约束保持同步
# 修改时必须同步更新: TaskState 枚举 + alembic 迁移 + 此常量
_ALLOWED_STATUS_VALUES: frozenset[str] = frozenset(s.value for s in TaskState)


def _new_cmd_id() -> str:
    """生成唯一命令 ID(模块级,供 stop/pause/resume + _run_task 共用)"""
    return f"cmd-{uuid4().hex[:12]}"


async def _resolve_default_agent_id() -> UUID | None:
    """解析默认 agent ID(V2 新增)

    从 agents 表查 is_default=TRUE 的 agent,不存在返回 None。
    """
    from app.repository.agent import AgentRepository

    if _pg_client is None:
        return None
    session = _pg_client.session()
    try:
        repo = AgentRepository(session)
        agent = await repo.get_default()
        await session.commit()
        return agent.id if agent else None
    except Exception:
        await session.rollback()
        log.warning("resolve_default_agent.failed", exc_info=True)
        return None
    finally:
        await session.close()


async def _resolve_single_agent_name(session: AsyncSession, agent_id: UUID | None) -> str:
    """解析单个 agent 的 display_name(V2 新增)"""
    if agent_id is None:
        return "browser-agent"
    from app.repository.agent import AgentRepository

    try:
        repo = AgentRepository(session)
        agent = await repo.get_by_id(agent_id)
        return agent.name if agent else "browser-agent"
    except Exception:
        return "browser-agent"


async def _resolve_agent_name_map(
    task_items: list[TaskOut],
) -> dict[UUID, str]:
    """批量获取 agent_id → display_name 映射,避免 N+1"""
    from app.repository.agent import AgentRepository

    agent_ids = [t.agent_id for t in task_items if t.agent_id is not None]
    if not agent_ids or _pg_client is None:
        return {}
    session = _pg_client.session()
    try:
        repo = AgentRepository(session)
        name_map = await repo.get_display_name_map(agent_ids)
        await session.commit()
        return name_map
    except Exception:
        await session.rollback()
        log.warning("resolve_agent_names.failed", exc_info=True)
        return {}
    finally:
        await session.close()


def init_policy_engine(llm_provider: ChatLLM) -> None:
    """初始化 PolicyEngine —— 在 FastAPI startup 后调用

    必须在 lifespan startup 完成后调用,因为需要 app.state.deps.llm。
    V2.5: PolicyEngine 保留作为 ReActEngine LLM 失败时的 fallback。
    """
    global _policy_engine
    _policy_engine = PolicyEngine(llm_provider)
    log.info("policy_engine.initialized")


def init_react_engine(llm_provider: ChatLLM, event_bus: EventBus) -> None:
    """初始化 ReActEngine —— V2.5 默认决策引擎

    必须在 lifespan startup 完成后调用。
    """
    global _react_engine
    _react_engine = ReActEngine(llm_provider, event_bus)
    log.info("react_engine.initialized")


async def init_timeline_recorder(pg: PostgresClient) -> None:
    """初始化 TimelineRecorder + 存储 pg client 引用 —— 在 lifespan startup 后调用

    必须 await 同步订阅,而不是 create_task 异步启动 —— EventBus 是 in-memory
    广播,没有重试/持久化:订阅时机晚于发布时机 = 永久丢失。
    """
    from app.runtime.timeline_recorder import TimelineRecorder as TR

    global _pg_client, _timeline_recorder
    _pg_client = pg
    _timeline_recorder = TR(_event_bus, pg, _task_state_mgr)
    # 同步订阅:让 create_task / stop_task 等后续流程发布 TASK_STATE_CHANGED 时,
    # TimelineRecorder._on_state_changed 一定已被注册,事件不会丢。
    # 原来用 asyncio.create_task(_timeline_recorder.start()) 异步启动,在
    # 启动竞争窗口(下一个 await 之前)发布的事件会丢失 —— 这是 2026-06-10
    # 状态不更新 bug 的根因之一。
    await _timeline_recorder.start()
    log.info("timeline_recorder.initialized")


def init_checkpoint_manager(pg: PostgresClient) -> None:
    """初始化 CheckpointManager —— 在 lifespan startup 后调用

    CheckpointManager 订阅 EventBus 的 ERROR / TASK_FINISHED / NEED_CONFIRM,
    在这些事件发生时自动保存 checkpoint。
    """
    global _checkpoint_manager
    _checkpoint_manager = CheckpointManager(_event_bus, pg, _task_state_mgr)
    asyncio.create_task(_checkpoint_manager.subscribe_all())
    log.info("checkpoint_manager.initialized")


def get_event_bus() -> EventBus:
    return _event_bus


def get_task_state_manager() -> TaskStateManager:
    return _task_state_mgr


def get_ws_manager() -> WebSocketManager:
    return _ws_manager


def get_checkpoint_manager() -> CheckpointManager | None:
    """获取 CheckpointManager 实例(用于生命周期管理)"""
    return _checkpoint_manager


def init_watchdog() -> ProcessWatchdog:
    """初始化 ProcessWatchdog —— 在 lifespan startup 后调用

    Watchdog 订阅 WORKER_HEARTBEAT 事件,并启动后台扫描协程。
    所有 BrowserTaskRunner 共享同一个 watchdog 实例。
    shutdown 时需调用 shutdown_watchdog() 清理订阅 + 停止扫描。
    """
    global _watchdog
    _watchdog = ProcessWatchdog(_event_bus)
    _event_bus.subscribe(EventType.WORKER_HEARTBEAT, _watchdog.on_heartbeat)
    _watchdog.start()
    log.info("watchdog.initialized")
    return _watchdog


async def shutdown_watchdog() -> None:
    """关闭 ProcessWatchdog —— 在 lifespan shutdown 时调用

    反序清理: unsubscribe → stop,防止 stop 后仍有事件触发 handler。
    """
    global _watchdog
    if _watchdog is None:
        return
    _event_bus.unsubscribe(EventType.WORKER_HEARTBEAT, _watchdog.on_heartbeat)
    await _watchdog.stop()
    log.info("watchdog.shutdown_complete")


def get_watchdog() -> ProcessWatchdog | None:
    """获取 ProcessWatchdog 实例(用于注入到 BrowserTaskRunner)"""
    return _watchdog


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

    # 解析 agent_id(V2: 不传则用 default agent)
    agent_id: UUID | None = payload.agent_id
    if agent_id is None and _pg_client is not None:
        agent_id = await _resolve_default_agent_id()
        if agent_id is None:
            from fastapi import HTTPException

            raise HTTPException(
                503, "No default agent available"
            )  # 503: 服务不可用(配置缺失),与现有 infra 异常分类一致

    # 写入 tasks 表(TimelineRecorder 需要 FK 引用)
    if _pg_client is not None:
        session = _pg_client.session()
        try:
            repo = TaskRepository(session)
            await repo.create(user_id, payload, task_id=UUID(task_id), agent_id=agent_id)
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
    # 显式落库兜底:TimelineRecorder 异步订阅 EventBus 写 DB 有 100ms 量级延迟,
    # 前端 5s 轮询在延迟窗口内会拉到旧值(pending),用户看到"刚创建 = 等待中"的
    # 体验割裂。这里 transition 之后立刻同步写一次 DB,与 TimelineRecorder
    # 双写是幂等的(白名单校验 + 仅 status 字段),不会冲突。
    await _persist_status_to_db(task_id, TaskState.RUNNING)

    # 启动 Worker —— 多任务并发:每个 task_id 独立 runner,登记到字典
    runner = BrowserTaskRunner(_event_bus, watchdog=_watchdog)
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
            # V2: 批量查 agent 展示名,替代硬编码 "browser-agent"
            name_map = await _resolve_agent_name_map(result.items)
            return {
                "items": [
                    _to_list_item(
                        t,
                        _task_state_mgr,
                        agent_name=(
                            name_map.get(t.agent_id, "browser-agent")
                            if t.agent_id is not None
                            else "browser-agent"
                        ),
                    )
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


def _to_list_item(
    t: TaskOut,
    state_mgr: TaskStateManager,
    agent_name: str = "browser-agent",
) -> dict:
    """把 Task ORM 转换为列表项 dict,status 字段做 runtime_state 兜底

    为什么需要兜底:
    - TimelineRecorder 异步订阅 EventBus,写 DB 有 IO 延迟
    - 启动竞态期间或 DB 写失败时,DB 的 status 会滞后于内存 TaskStateManager
    - 与 get_task 端的 status 字段处理保持一致(第 808 行的同样模式)

    兜底规则:
    - runtime_state 是非 PENDING 的"已知最新态" → 用 runtime_state
    - runtime_state 是 PENDING(或未初始化) → 用 DB 值(避免误把已写入的
      终态改回 PENDING,因为 TaskStateManager 默认值是 PENDING)
    """
    runtime_state = state_mgr.get_state(str(t.id))
    # 仅当 runtime_state 不是默认 PENDING 时,才认为内存比 DB 更新
    # 这样可以避免:
    # 1) 进程刚启动,TaskStateManager 还没 rehydrate 完成时,把 DB 已落库的
    #    cancelled/completed 错改回 pending
    # 2) _task_state_mgr 是模块级单例但 TaskStateManager 是新进程实例的场景
    status = runtime_state.value if runtime_state != TaskState.PENDING else t.status
    # 防御性白名单:DB 里可能存在历史脏数据(CHECK 约束 2026-06-10 才加),
    # 这里兜一次,非法值在 list_tasks 阶段就过滤,避免污染前端
    # (StatusBadge 对未知值会显示"未知" + warn,体验很差)
    if status not in _ALLOWED_STATUS_VALUES:
        log.warning(
            "list_tasks.invalid_status_filtered",
            task_id=str(t.id),
            bad_status=status,
        )
        status = "failed"  # 安全降级:前端能识别"失败"态,且终态不再误显示为"在跑"
    return {
        "id": str(t.id),
        "goal": t.goal,
        "agentName": agent_name,
        "status": status,
        "createdAt": t.created_at.isoformat(),
        "updatedAt": t.updated_at.isoformat(),
        "costUsd": 0,
    }


async def _persist_status_to_db(task_id: str, status: TaskState) -> None:
    """把 status 显式同步写回 tasks 表 —— transition 后的兜底落库。

    为什么需要显式落库(因为 TimelineRecorder 已在订阅):
    - TimelineRecorder 异步订阅 + 异步写 DB,有 100ms 量级延迟
    - 启动竞态或 handler 异常时,DB 状态会滞后
    - 用户能从 list_tasks 看到的状态,必须有同步落库做"最终一致性"兜底
    - 与 TimelineRecorder 双写是幂等的(TimelineRecorder._on_state_changed
      调 update_status,白名单校验 + 仅 status 字段,后写赢)

    失败处理:
    - DB 不可用 / task_id 非法 UUID / 任何 IO 错误 → 仅记录 warning,
      不抛异常(transition 已成功,内存状态正确,前端 5s 轮询下次会拿到 runtime fallback)
    """
    if _pg_client is None:
        return
    try:
        task_uuid = UUID(task_id)
    except ValueError:
        log.warning("persist_status.invalid_task_id", task_id=task_id)
        return

    session = _pg_client.session()
    try:
        repo = TaskRepository(session)
        await repo.update_status(task_uuid, TaskUpdate(status=status.value))
        await session.commit()
    except Exception:
        await session.rollback()
        log.warning(
            "persist_status.failed",
            task_id=task_id,
            target_status=status.value,
            exc_info=True,
        )
    finally:
        await session.close()


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
    """将 Worker action 类型映射为前端 TimelineStepKind

    映射规则:
    - think: LLM 思考/推理类动作(当前 Worker 不单独上报,预留)
    - tool: 浏览器操作类(navigate/click/input_text/screenshot/extract/scroll)
    - observe: 错误/观察类(ERROR/STEP_FAILED)
    - human: 人工确认类(NEED_CONFIRM 事件触发)
    - complete: 任务完成类
    """
    if action in ("navigate", "click", "input_text", "screenshot", "extract", "scroll"):
        return "tool"
    if action.startswith("ERROR") or action.startswith("STEP_FAILED"):
        return "observe"
    if action in ("NEED_CONFIRM", "confirm", "human_input"):
        return "human"
    if action in ("TASK_FINISHED", "complete", "done"):
        return "complete"
    if action in ("think", "reason", "plan"):
        return "think"
    # 默认归为 tool —— 未知动作类型大概率是新的浏览器操作
    return "tool"


@router.post("/{task_id}/messages")
async def send_task_message(
    task_id: str,
    payload: TaskMessageCreate,
    user_id: UUID = Depends(get_current_user_id),
) -> TaskMessageOut:
    """用户向 Agent 发送指令 —— 半自动模式核心端点

    前端 postTaskMessage() 调用此端点,实现:
    - 半自动模式:用户确认/拒绝/反馈
    - 运行中追加指令:用户补充说明

    实现方式:根据任务当前状态决定发送哪种 Command:
    - WAITING_CONFIRM + 用户确认 → CONTINUE(approved=True, feedback=content)
    - WAITING_CONFIRM + 用户拒绝 → REJECT(reason=content)
    - RUNNING → CONTINUE(feedback=content),让 PolicyEngine 考虑用户反馈
    """
    # 生成消息 ID
    msg_id = str(uuid4())
    now_iso = datetime.now(UTC).isoformat()

    # 查询任务当前状态
    current_state = _task_state_mgr.get_state(task_id)

    # 查找活跃 runner
    runner = _active_runners.get(task_id)

    if runner is None:
        # runner 不存在可能是任务已结束,仍返回用户消息(前端需要确认)
        log.warning("message.no_active_runner", task_id=task_id, state=current_state.value)
        return TaskMessageOut(
            id=msg_id,
            task_id=task_id,
            role="user",
            content=payload.content,
            created_at=now_iso,
        )

    # ── V2.5: 按状态分流 ──
    if current_state == TaskState.RUNNING:
        # V2.5: 用户中途插话 → INTERRUPT Worker (完全替代 V2.0 的 CONTINUE+feedback)
        cmd = Command(
            command_id=f"cmd-{uuid4().hex[:12]}",
            type=CommandType.INTERRUPT,
            payload=InterruptPayload(
                reason="user_interrupt",
                user_message=payload.content,
            ).model_dump(),
        )
        await _task_state_mgr.transition(
            task_id, TaskState.WAITING_USER, f"用户中断: {payload.content[:80]}"
        )
        await _persist_status_to_db(task_id, TaskState.WAITING_USER)
        await runner.send_command(cmd)
        log.info("message.user_interrupt", task_id=task_id, content=payload.content[:80])

    elif current_state == TaskState.WAITING_USER:
        # V2.5: 用户回复 Agent 求助 / 继续中断
        prev_interrupt = _task_state_mgr.get_context(task_id, "interrupt_payload") or {}
        cmd = Command(
            command_id=f"cmd-{uuid4().hex[:12]}",
            type=CommandType.RESUME,
            payload=ResumePayload(
                feedback=payload.content,
                ask_human_block_type=prev_interrupt.get("ask_human_block_type", ""),
                ask_human_question=prev_interrupt.get("ask_human_question", ""),
                previous_interrupt_reason=prev_interrupt.get("reason", ""),
            ).model_dump(),
        )
        await _task_state_mgr.transition(
            task_id, TaskState.RUNNING, f"用户回复: {payload.content[:80]}"
        )
        await _persist_status_to_db(task_id, TaskState.RUNNING)
        await runner.send_command(cmd)
        log.info("message.user_resume", task_id=task_id, content=payload.content[:80])

    elif current_state == TaskState.WAITING_CONFIRM:
        # V2.5: 保留 V2.0 的 reject_keywords 启发式
        reject_keywords = {"拒绝", "取消", "不要", "no", "reject", "cancel", "stop"}
        is_reject = any(kw in payload.content.lower() for kw in reject_keywords)

        if is_reject:
            cmd = Command(
                command_id=f"cmd-{uuid4().hex[:12]}",
                type=CommandType.REJECT,
                payload={"reason": payload.content},
            )
            await _task_state_mgr.transition(
                task_id, TaskState.STOPPING, f"用户拒绝: {payload.content[:80]}"
            )
        else:
            cmd = Command(
                command_id=f"cmd-{uuid4().hex[:12]}",
                type=CommandType.CONTINUE,
                payload={"approved": True, "feedback": payload.content},
            )
            await _task_state_mgr.transition(
                task_id, TaskState.RUNNING, f"用户确认: {payload.content[:80]}"
            )
        await runner.send_command(cmd)
        log.info("message.confirm_response", task_id=task_id, is_reject=is_reject)

    else:
        # PAUSED / 终态: 拒绝
        log.warning(
            "message.task_not_accepting",
            task_id=task_id,
            state=current_state.value,
        )
        raise HTTPException(400, f"任务状态 {current_state.value} 不接受消息")

    return TaskMessageOut(
        id=msg_id,
        task_id=task_id,
        role="user",
        content=payload.content,
        created_at=now_iso,
    )


# ═══════════════════════════════════════════════════════════════
# 任务控制端点 —— 停止 / 暂停 / 继续
#
# 设计要点(2026-06-10 新增):
# - 解决"任务卡死时用户无法从 UI 控制"的逃生通道
# - 三个接口都是幂等的(对终态任务调用返回 accepted=False, 不抛错)
# - 状态转换合法性由 TaskStateManager 校验(走标准 transition() 路径)
# - stop 发送 CommandType.STOP 给 Worker,Worker 优雅退出
# - pause 发送 CommandType.STOP 但状态停留在 PAUSED(不转 STOPPING, 保留 resume 机会)
# - resume 当前 V1 只做状态机恢复(PAUSED→RUNNING);真正的 Worker 重启是 V2 工作
# ═══════════════════════════════════════════════════════════════


@router.post("/{task_id}/stop", response_model=TaskActionResponse)
async def stop_task(
    task_id: str,
    user_id: UUID = Depends(get_current_user_id),
) -> TaskActionResponse:
    """停止任务 —— 终止 Worker,任务转为 CANCELLED

    行为:
    1. RUNNING/WAITING_CONFIRM/PAUSED → STOPPING → CANCELLED(标准路径)
    2. 终态任务调用 → accepted=False,不抛错(幂等)
    3. 找到活跃 runner 时发送 STOP 命令;没找到时只更新状态(Worker 可能已死)

    为什么不抛 404: 用户视角下"任务已经结束"和"任务不存在"在 UI 上难以区分,
    且从 dashboard 列表里看到的 task_id 一定存在 —— 终态路径已覆盖多数情况。
    """
    _ = user_id  # 当前版本不做所有权校验,后续接 ownership 时再启用
    current = _task_state_mgr.get_state(task_id)

    # 终态: 幂等返回
    if current in (
        TaskState.CANCELLED,
        TaskState.COMPLETED,
        TaskState.FAILED,
    ):
        return TaskActionResponse(
            task_id=task_id,
            state=current.value,
            accepted=False,
            reason=f"任务已处于终态 ({current.value})",
        )

    # 走标准路径 STOPPING → CANCELLED
    # InvalidTransitionError 由 TaskStateManager 内部处理(已经在转换表内)
    runner = _active_runners.get(task_id)
    target_state = TaskState.STOPPING
    try:
        await _task_state_mgr.transition(task_id, target_state, "用户主动停止")
        # 显式落库兜底:见 _persist_status_to_db 注释
        await _persist_status_to_db(task_id, target_state)
    except Exception as e:
        return TaskActionResponse(
            task_id=task_id,
            state=current.value,
            accepted=False,
            reason=f"状态转换失败: {e}",
        )

    # 通知 Worker 退出(在状态转换后发,避免 Worker 收到 STOP 但状态机还没准备好)
    if runner is not None:
        try:
            await runner.send_command(
                Command(
                    command_id=_new_cmd_id(),
                    type=CommandType.STOP,
                    payload={"reason": "user_requested"},
                )
            )
        except Exception:
            log.warning("stop.send_command_failed", task_id=task_id, exc_info=True)

    log.info("task.stop_accepted", task_id=task_id, prev_state=current.value)
    return TaskActionResponse(
        task_id=task_id,
        state=TaskState.STOPPING.value,
        accepted=True,
    )


@router.post("/{task_id}/pause", response_model=TaskActionResponse)
async def pause_task(
    task_id: str,
    user_id: UUID = Depends(get_current_user_id),
) -> TaskActionResponse:
    """暂停任务 —— RUNNING/WAITING_CONFIRM → PAUSED,Worker 收到 STOP 退出

    V1 实现范围:
    - 状态机:支持 RUNNING/WAITING_CONFIRM → PAUSED
    - Worker:Worker 收到 STOP 后会退出(因为 Worker 暂未实现 PAUSE 协议)
    - 因此 PAUSED 状态表示"用户希望暂停",Worker 实际已退出
    - 真正的"保留 Worker 进程 / 续跑"是 V2 范围,需配合 Checkpoint 持久化

    V2 TODO:
    - Worker 实现 PAUSE 命令处理(挂起当前 step,保留内存状态)
    - 持久化 Checkpoint,resume 时拉起新 Worker 续跑
    """
    _ = user_id
    current = _task_state_mgr.get_state(task_id)

    # 终态 / 已暂停:幂等返回
    if current in (
        TaskState.CANCELLED,
        TaskState.COMPLETED,
        TaskState.FAILED,
    ):
        return TaskActionResponse(
            task_id=task_id,
            state=current.value,
            accepted=False,
            reason=f"任务已处于终态 ({current.value})",
        )
    if current == TaskState.PAUSED:
        return TaskActionResponse(
            task_id=task_id,
            state=TaskState.PAUSED.value,
            accepted=False,
            reason="任务已经处于 PAUSED 状态",
        )

    # 合法转换: RUNNING/WAITING_CONFIRM → PAUSED
    try:
        await _task_state_mgr.transition(task_id, TaskState.PAUSED, "用户暂停任务")
        # 显式落库兜底:见 _persist_status_to_db 注释
        await _persist_status_to_db(task_id, TaskState.PAUSED)
    except Exception as e:
        return TaskActionResponse(
            task_id=task_id,
            state=current.value,
            accepted=False,
            reason=f"状态转换失败: {e}",
        )

    # 通知 Worker 退出(V1:Worker 不支持 PAUSE,所以"暂停"= "停止" + 保留状态)
    runner = _active_runners.get(task_id)
    if runner is not None:
        try:
            await runner.send_command(
                Command(
                    command_id=_new_cmd_id(),
                    type=CommandType.STOP,
                    payload={"reason": "user_paused"},
                )
            )
        except Exception:
            log.warning("pause.send_command_failed", task_id=task_id, exc_info=True)

    log.info("task.pause_accepted", task_id=task_id, prev_state=current.value)
    return TaskActionResponse(
        task_id=task_id,
        state=TaskState.PAUSED.value,
        accepted=True,
    )


@router.post("/{task_id}/resume", response_model=TaskActionResponse)
async def resume_task(
    task_id: str,
    user_id: UUID = Depends(get_current_user_id),
) -> TaskActionResponse:
    """继续任务 —— PAUSED → RUNNING

    V1 实现范围:
    - 状态机:支持 PAUSED → RUNNING
    - Worker:V1 **不会**自动拉起新 Worker(需 Checkpoint 协议,见 pause V2 TODO)
    - 前端在 PAUSED 状态下点"继续"只更新状态机,需要用户主动发新指令才会动

    V2 TODO:
    - 加载 Checkpoint,创建新 BrowserTaskRunner 续跑
    - 现状对用户透明:前端按钮在 PAUSED 时显示"继续"和"停止",点"继续"后
      可继续用 ChatInput 发送新指令作为"新目标",但 Worker 已退出的情况下
      Agent 不会继续执行原目标。
    """
    _ = user_id
    current = _task_state_mgr.get_state(task_id)

    # 终态:不接受
    if current in (
        TaskState.CANCELLED,
        TaskState.COMPLETED,
        TaskState.FAILED,
    ):
        return TaskActionResponse(
            task_id=task_id,
            state=current.value,
            accepted=False,
            reason=f"任务已处于终态,无法继续 ({current.value})",
        )

    # 非 PAUSED: 不接受(避免把 RUNNING 又切回 RUNNING)
    if current != TaskState.PAUSED:
        return TaskActionResponse(
            task_id=task_id,
            state=current.value,
            accepted=False,
            reason=f"仅 PAUSED 状态可以 resume,当前 {current.value}",
        )

    # PAUSED → RUNNING(先转换再启动 Worker)
    try:
        await _task_state_mgr.transition(task_id, TaskState.RUNNING, "用户继续任务")
        # 显式落库兜底:见 _persist_status_to_db 注释
        await _persist_status_to_db(task_id, TaskState.RUNNING)
    except Exception as e:
        return TaskActionResponse(
            task_id=task_id,
            state=current.value,
            accepted=False,
            reason=f"状态转换失败: {e}",
        )

    # 从 checkpoint 加载目标并拉起新 Worker
    if _checkpoint_manager is not None:
        try:
            task_uuid = UUID(task_id)
        except ValueError:
            return TaskActionResponse(
                task_id=task_id,
                state=TaskState.RUNNING.value,
                accepted=False,
                reason="无效 task_id 格式",
            )

        resume_state = await _checkpoint_manager.resume_from_latest(task_uuid)
        if resume_state is None:
            log.warning("resume.no_checkpoint", task_id=task_id)
            return TaskActionResponse(
                task_id=task_id,
                state=TaskState.RUNNING.value,
                accepted=True,
                reason="状态已恢复,但无 checkpoint,Worker 需手动触发",
            )

        # 重建 TaskContext
        context = TaskContext(
            task_id=task_id,
            goal=resume_state.task.goal,
            skill="browser",
            user_id=user_id,
        )

        runner = BrowserTaskRunner(_event_bus, watchdog=_watchdog)
        _active_runners[task_id] = runner
        asyncio.create_task(_run_task(runner, context, task_id, resume_state=resume_state))

        log.info(
            "task.resume_with_checkpoint",
            task_id=task_id,
            step=resume_state.task.current_step_index,
        )
        return TaskActionResponse(
            task_id=task_id,
            state=TaskState.RUNNING.value,
            accepted=True,
            reason=f"从 checkpoint 恢复,继续执行: {resume_state.task.goal[:50]}",
        )

    # 无 CheckpointManager: 仅状态恢复
    log.info("task.resume_accepted", task_id=task_id, prev_state=current.value)
    return TaskActionResponse(
        task_id=task_id,
        state=TaskState.RUNNING.value,
        accepted=True,
        reason="状态已恢复,但 CheckpointManager 未就绪",
    )


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    user_id: UUID = Depends(get_current_user_id),
) -> dict:
    """查询任务详情 —— 返回与前端 TaskDetail 对齐的完整字段

    数据源合并策略:
    - DB(tasks 表): goal, created_at, updated_at, result 等持久化字段
    - 内存(TaskStateManager): 实时状态(比 DB 更及时)
    - 内存(_active_runners): 运行时步骤/截图/技能调用

    字段名对齐前端:
    - 后端 task_id → 前端 id
    - 后端 state → 前端 status
    - 后端 created_at → 前端 createdAt(camelCase)
    """
    # 内存状态(实时)
    runtime_state = _task_state_mgr.get_state(task_id)

    # DB 持久化数据
    db_task: TaskOut | None = None
    db_steps: list[TaskStepOut] = []
    agent_name = "browser-agent"  # V2 兜底:DB 不可用时回退硬编码

    if _pg_client is not None:
        try:
            task_uuid = UUID(task_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid task_id format") from None

        session = _pg_client.session()
        try:
            task_repo = TaskRepository(session)
            db_task = await task_repo.get_by_id(task_uuid)

            # 校验任务归属
            if db_task is None or db_task.user_id != user_id:
                raise HTTPException(status_code=404, detail="Task not found")

            # V2: 查询 agent 展示名(替代硬编码 "browser-agent")
            agent_name = await _resolve_single_agent_name(session, db_task.agent_id)

            # 查询步骤
            step_repo = TaskStepRepository(session)
            db_steps = await step_repo.list_by_task(task_uuid)
        except HTTPException:
            raise
        except Exception:
            await session.rollback()
            log.warning("task.get_query_failed", task_id=task_id, exc_info=True)
        finally:
            await session.close()

    if db_task is None:
        # DB 无记录(可能纯内存任务),返回运行时数据
        return {
            "id": task_id,
            "goal": "",
            "agentName": "browser-agent",
            "status": runtime_state.value,
            "createdAt": "",
            "updatedAt": "",
            "costUsd": 0,
            "totalDurationSec": 0,
            "totalTokens": 0,
            "steps": [],
            "screenshots": [],
            "skillCalls": [],
        }

    # 合并 DB + 运行时数据
    # status 优先用运行时状态(更实时),回退到 DB 状态
    status = runtime_state.value if runtime_state != TaskState.PENDING else db_task.status

    # 构造步骤列表(与前端 TaskStep 对齐, V2.5: +step_type/reasoning)
    steps = [
        {
            "index": s.step_index,
            "kind": _step_kind_from_action(s.action),
            "title": s.action,
            "summary": (s.result or {}).get("summary", ""),
            "startedAt": "",
            "durationMs": s.duration_ms or (s.result or {}).get("duration_ms", 0) or 0,
            "tokens": s.tokens_used or 0,
            "stepType": s.step_type,
            "reasoning": s.reasoning,
            "llmLatencyMs": s.llm_latency_ms,
            "modelUsed": s.model_name,
        }
        for s in db_steps
    ]

    # 从 result JSONB 提取截图和技能调用
    result_data = db_task.result or {}
    screenshots = result_data.get("screenshots", [])
    skill_calls = result_data.get("skill_calls", [])

    return {
        "id": str(db_task.id),
        "goal": db_task.goal,
        "agentName": agent_name,
        "status": status,
        "createdAt": db_task.created_at.isoformat(),
        "updatedAt": db_task.updated_at.isoformat()
        if db_task.updated_at
        else db_task.created_at.isoformat(),
        "costUsd": float(db_task.total_cost_usd or 0),  # V2.5: 真实成本
        "modelUsed": db_task.llm_model_used,  # V2.5: 使用的模型
        "totalDurationSec": result_data.get("total_duration_sec", 0) or 0,
        "totalTokens": db_task.total_tokens or 0,  # V2.5: DB 直接值
        "steps": steps,
        "screenshots": screenshots,
        "skillCalls": skill_calls,
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
    resume_state: FullCheckpointState | None = None,
) -> None:
    """后台执行循环: STEP_COMPLETE → PolicyEngine.decide → CONTINUE, 直到终止

    终止条件(任一触发则发送 STOP):
    - PolicyEngine.decide() 返回 is_terminal=True
    - step_index >= max_steps
    - 连续 3 次相同动作(类型+目标一致, 防死循环)
    - 连续 3 次错误(不可恢复)
    - Worker TASK_FINISHED(正常/异常结束)
    - 总超时

    resume_state: 从 checkpoint 恢复时传入,用于预填充 trajectory
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
    # V2.5: 最近错误滑窗 (每 task 独立, 进程内 deque)
    from collections import deque

    recent_errors: deque[str] = deque(maxlen=3)
    # asyncio.Queue 保证并发安全: 多个 handler 同时 put 不会丢事件
    event_queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue()

    # 加载用户偏好(长期记忆) — 注入 PolicyEngine system prompt
    user_prefs: list | None = None  # list[UserPreference]
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

    # Resume: 从 checkpoint 恢复 trajectory 步数
    if resume_state is not None:
        trajectory.step_index = resume_state.task.current_step_index
        log.info(
            "task.resume_trajectory",
            task_id=task_id,
            step_index=trajectory.step_index,
        )

    # ── 事件处理内联函数(必须 async,EventBus 类型签名要求) ──
    async def _on_step_complete(event: RuntimeEvent) -> None:
        if event.task_id == task_id:
            await event_queue.put(event)

    async def _on_error(event: RuntimeEvent) -> None:
        if event.task_id == task_id:
            await event_queue.put(event)
            # V2.5: 维护最近错误滑窗 (给 ReActEngine observation 用)
            msg = event.payload.get("message", "")
            if msg:
                recent_errors.append(msg)

    async def _on_task_finished(event: RuntimeEvent) -> None:
        if event.task_id == task_id:
            await event_queue.put(event)

    async def _on_watchdog_timeout(event: RuntimeEvent) -> None:
        if event.task_id == task_id:
            await event_queue.put(event)

    async def _on_need_human(event: RuntimeEvent) -> None:
        """V2.5: Worker 发射 NEED_HUMAN 事件后, Runtime 转 WAITING_USER"""
        if event.task_id == task_id:
            await event_queue.put(event)

    async def _on_resumed(event: RuntimeEvent) -> None:
        """V2.5: Worker 从中断/暂停恢复 (用户已响应 WAITING_USER)"""
        if event.task_id == task_id:
            await event_queue.put(event)

    # 先订阅再启动(防竞态)
    _event_bus.subscribe(EventType.STEP_COMPLETE, _on_step_complete)
    _event_bus.subscribe(EventType.ERROR, _on_error)
    _event_bus.subscribe(EventType.TASK_FINISHED, _on_task_finished)
    _event_bus.subscribe(EventType.WATCHDOG_TIMEOUT, _on_watchdog_timeout)
    _event_bus.subscribe(EventType.NEED_HUMAN, _on_need_human)  # V2.5
    _event_bus.subscribe(EventType.RESUMED, _on_resumed)  # V2.5

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

                # 追加 Trajectory(供决策引擎参考)
                trajectory.add_step(
                    action=ActionDetail(
                        type=payload.get("action", ""),
                        description=payload.get("summary", ""),
                    ),
                    url=payload.get("url"),
                    title=payload.get("title"),
                    summary=payload.get("summary", ""),
                )

                # V2.5: 构建 ObservationState (从 STEP_COMPLETE payload 提取)
                observation = ObservationState(
                    url=payload.get("url"),
                    title=payload.get("title"),
                    dom_summary=payload.get("dom_summary", ""),
                    visible_text=payload.get("visible_text", ""),
                    recent_errors=list(recent_errors),
                    step_index=step_index,
                )

                # V2.5: 合成 OBSERVE_COMPLETE 事件 (给 TimelineRecorder 等)
                await _event_bus.publish(
                    RuntimeEvent(
                        version="2.0.0",
                        event_id=f"observe-{step_index}",
                        event=EventType.OBSERVE_COMPLETE,
                        ts=datetime.now(UTC),
                        task_id=task_id,
                        payload={
                            "step_index": step_index,
                            "url": observation.url,
                            "title": observation.title,
                            "dom_summary": observation.dom_summary,
                            "visible_text": observation.visible_text,
                        },
                    )
                )

                # Checkpoint: 判定是否保存当前进度(定期存 + 关键操作)
                if _checkpoint_manager is not None:
                    from app.runtime.checkpoint_manager import CheckpointManager

                    action_type = payload.get("action", "")
                    if CheckpointManager.should_save_on_step(step_index, action_type):
                        await _checkpoint_manager.save_task_checkpoint(
                            task_id=task_id,
                            goal=context.goal,
                            step_index=step_index,
                            trajectory_summary=trajectory.summary_for_prompt(),
                            checkpoint_type="auto",
                            action_result=payload.get("summary", ""),
                            action_url=payload.get("url"),
                            page_title=payload.get("title"),
                            preferences=user_prefs,
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

                # V2.5: ReActEngine 决策 (优先), 失败时 fallback 到 PolicyEngine
                decision = None
                if _react_engine is not None:
                    try:
                        decision = await _react_engine.decide(
                            context.goal,
                            trajectory,
                            observation,
                            task_id=task_id,
                            preferences=user_prefs,
                        )
                    except Exception:
                        log.warning("react_engine.decide_failed", task_id=task_id, exc_info=True)
                        # Fallback 到 PolicyEngine
                        if _policy_engine is not None:
                            try:
                                decision = await _policy_engine.decide(
                                    context.goal, trajectory, preferences=user_prefs
                                )
                            except Exception:
                                log.warning(
                                    "policy_engine.decide_failed", task_id=task_id, exc_info=True
                                )
                elif _policy_engine is not None:
                    try:
                        decision = await _policy_engine.decide(
                            context.goal, trajectory, preferences=user_prefs
                        )
                    except Exception:
                        log.warning("policy_engine.decide_failed", task_id=task_id, exc_info=True)

                if decision is None:
                    result_state = TaskState.FAILED
                    result_reason = "所有决策引擎均失败"
                    await runner.send_command(
                        Command(
                            command_id=_new_cmd_id(),
                            type=CommandType.STOP,
                            payload={"reason": "all_engines_failed"},
                        )
                    )
                    break

                # ── V2.5: 决策类型路由 ──
                if decision.decision_type == ReActDecisionType.DONE.value or decision.is_terminal:
                    log.info("react.done_detected", task_id=task_id, step=step_index)
                    await runner.send_command(
                        Command(
                            command_id=_new_cmd_id(),
                            type=CommandType.STOP,
                            payload={"reason": "goal_achieved"},
                        )
                    )
                    result_state = TaskState.COMPLETED
                    result_reason = decision.reasoning
                    break

                if decision.decision_type == ReActDecisionType.ASK_HUMAN.value:
                    # V2.5: Agent 求助 → WAITING_USER
                    block_type = decision.action.value or "other"
                    question = decision.action.description
                    log.info(
                        "react.ask_human",
                        task_id=task_id,
                        block_type=block_type,
                        question=question[:80],
                    )

                    # 保存 ASK_HUMAN 上下文 (供 resume 时回传)
                    _task_state_mgr.set_context(
                        task_id,
                        key="interrupt_payload",
                        value={
                            "ask_human_block_type": block_type,
                            "ask_human_question": question,
                        },
                    )
                    await _task_state_mgr.transition(
                        task_id, TaskState.WAITING_USER, f"Agent 求助: {question[:80]}"
                    )
                    await _persist_status_to_db(task_id, TaskState.WAITING_USER)

                    # 通知 Worker 中断
                    await runner.send_command(
                        Command(
                            command_id=_new_cmd_id(),
                            type=CommandType.INTERRUPT,
                            payload=InterruptPayload(
                                reason="agent_ask_human",
                                ask_human_block_type=block_type,
                                ask_human_question=question,
                            ).model_dump(),
                        )
                    )

                    # V2.5: 等待用户响应 (超时 300s → FAILED)
                    # 收到 RESUMED 后重新决策, 支持多轮 ASK_HUMAN
                    while True:
                        try:
                            response_event = await asyncio.wait_for(
                                event_queue.get(), timeout=WAITING_USER_TIMEOUT
                            )
                        except TimeoutError:
                            result_reason = "用户 300s 未响应 Agent 求助"
                            log.warning("task.wait_user_timeout", task_id=task_id)
                            await _task_state_mgr.transition(
                                task_id, TaskState.FAILED, f"wait_user_timeout: {result_reason}"
                            )
                            if _checkpoint_manager is not None:
                                await _checkpoint_manager.save_task_checkpoint(
                                    task_id=task_id,
                                    goal=context.goal,
                                    step_index=trajectory.step_index,
                                    trajectory_summary=trajectory.summary_for_prompt(),
                                    checkpoint_type="user_unresponsive",
                                    action_result=question,
                                )
                            break
                        if response_event.event == EventType.TASK_FINISHED:
                            break

                        # 用户已响应 → 重新决策
                        # 注意: observation 可能已过时 (用户在页面上操作后页面状态变了)
                        # 但当前 Worker RESUME 后会执行新动作并返回 STEP_COMPLETE,
                        # STEP_COMPLETE 处理时会更新 observation, 所以此处用旧 observation
                        # 做决策是可接受的——决策基于 trajectory + 当前已知页面状态,
                        # 如果页面确实变了, 下一个 STEP_COMPLETE 会修正
                        _new_dec = None
                        if _react_engine is not None:
                            try:
                                _new_dec = await _react_engine.decide(
                                    context.goal,
                                    trajectory,
                                    observation,
                                    task_id=task_id,
                                    preferences=user_prefs,
                                )
                            except Exception:
                                log.warning(
                                    "react_engine.resume_decide_failed",
                                    task_id=task_id,
                                    exc_info=True,
                                )
                        if _new_dec is None and _policy_engine is not None:
                            try:
                                _new_dec = await _policy_engine.decide(
                                    context.goal,
                                    trajectory,
                                    preferences=user_prefs,
                                )
                            except Exception:
                                log.warning(
                                    "policy_engine.resume_decide_failed",
                                    task_id=task_id,
                                    exc_info=True,
                                )
                        if _new_dec is None:
                            result_state = TaskState.FAILED
                            result_reason = "用户响应后所有决策引擎均失败"
                            await runner.send_command(
                                Command(
                                    command_id=_new_cmd_id(),
                                    type=CommandType.STOP,
                                    payload={"reason": "all_engines_failed"},
                                )
                            )
                            break

                        if (
                            _new_dec.decision_type == ReActDecisionType.DONE.value
                            or _new_dec.is_terminal
                        ):
                            await runner.send_command(
                                Command(
                                    command_id=_new_cmd_id(),
                                    type=CommandType.STOP,
                                    payload={"reason": "goal_achieved"},
                                )
                            )
                            result_state = TaskState.COMPLETED
                            result_reason = _new_dec.reasoning
                            break

                        if _new_dec.decision_type == ReActDecisionType.ASK_HUMAN.value:
                            block_type = _new_dec.action.value or "other"
                            question = _new_dec.action.description
                            _task_state_mgr.set_context(
                                task_id,
                                "interrupt_payload",
                                value={
                                    "ask_human_block_type": block_type,
                                    "ask_human_question": question,
                                },
                            )
                            await _task_state_mgr.transition(
                                task_id,
                                TaskState.WAITING_USER,
                                f"Agent 再次求助: {question[:80]}",
                            )
                            await _persist_status_to_db(task_id, TaskState.WAITING_USER)
                            await runner.send_command(
                                Command(
                                    command_id=_new_cmd_id(),
                                    type=CommandType.INTERRUPT,
                                    payload=InterruptPayload(
                                        reason="agent_ask_human",
                                        ask_human_block_type=block_type,
                                        ask_human_question=question,
                                    ).model_dump(),
                                )
                            )
                            continue  # 等用户再次响应

                        # ACT 路径: 死循环检测 + 发送 CONTINUE
                        decision = _new_dec
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

                        await runner.send_command(
                            Command(
                                command_id=_new_cmd_id(),
                                type=CommandType.CONTINUE,
                                payload={"action": next_action.model_dump()},
                            )
                        )
                        log.info(
                            "task.continue_after_resume",
                            task_id=task_id,
                            next=next_action.type,
                        )
                        break  # 回到主循环等下一个事件

                    if result_state not in (TaskState.FAILED, TaskState.COMPLETED):
                        continue  # 已发 CONTINUE, 回主循环
                    break  # terminal: 主循环终止

                # ── ACT 路径 ──
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
                    decision_type=decision.decision_type,
                )

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

            elif event.event == EventType.WATCHDOG_TIMEOUT:
                payload = event.payload
                log.error(
                    "task.watchdog_timeout",
                    task_id=task_id,
                    last_seq=payload.get("last_heartbeat_seq"),
                    seconds_since_last=payload.get("seconds_since_last"),
                )
                result_state = TaskState.FAILED
                result_reason = "Worker 心跳超时,进程可能死锁"

                # 主动停止 Worker,防止僵尸进程(心跳丢失但进程仍存活)
                try:
                    await runner.stop_task()
                except Exception:
                    log.warning("task.watchdog_stop_failed", task_id=task_id, exc_info=True)

                # 超时前保存 checkpoint(标记 error 类型,可供人工恢复)
                if _checkpoint_manager is not None:
                    from app.runtime.checkpoint_manager import CheckpointManager

                    await _checkpoint_manager.save_task_checkpoint(
                        task_id=task_id,
                        goal=context.goal,
                        step_index=trajectory.step_index,
                        trajectory_summary=trajectory.summary_for_prompt(),
                        checkpoint_type="error",
                        action_result="任务因心跳超时强制结束",
                    )
                break

            elif event.event == EventType.NEED_HUMAN:
                # V2.5: Worker 端直接发射 NEED_HUMAN (BrowserSkill 检测到阻塞)
                payload = event.payload
                block_type = payload.get("block_type", "other")
                question = payload.get("question", "")

                _task_state_mgr.set_context(
                    task_id,
                    key="interrupt_payload",
                    value={
                        "ask_human_block_type": block_type,
                        "ask_human_question": question,
                    },
                )
                await _task_state_mgr.transition(
                    task_id, TaskState.WAITING_USER, f"Worker 检测到阻塞: {block_type}"
                )
                await _persist_status_to_db(task_id, TaskState.WAITING_USER)

                # 通知 Worker 中断 (与 ASK_HUMAN 路径保持一致, 同步 Worker 状态机)
                await runner.send_command(
                    Command(
                        command_id=_new_cmd_id(),
                        type=CommandType.INTERRUPT,
                        payload=InterruptPayload(
                            reason="worker_need_human",
                            ask_human_block_type=block_type,
                            ask_human_question=question,
                        ).model_dump(),
                    )
                )

                # 等待用户响应
                try:
                    await asyncio.wait_for(event_queue.get(), timeout=WAITING_USER_TIMEOUT)
                    continue  # 继续循环, ReActEngine 重新规划
                except TimeoutError:
                    result_reason = "用户 300s 未响应 Worker 阻塞"
                    log.warning("task.need_human_timeout", task_id=task_id)
                    # 超时保存 checkpoint (与 ASK_HUMAN 路径一致)
                    if _checkpoint_manager is not None:
                        await _checkpoint_manager.save_task_checkpoint(
                            task_id=task_id,
                            goal=context.goal,
                            step_index=trajectory.step_index,
                            trajectory_summary=trajectory.summary_for_prompt(),
                            checkpoint_type="user_unresponsive",
                            action_result=f"NEED_HUMAN 超时: {block_type} - {question[:80]}",
                        )
                    await _task_state_mgr.transition(
                        task_id, TaskState.FAILED, f"wait_user_timeout: {result_reason}"
                    )
                    break

            elif event.event == EventType.TASK_FINISHED:
                payload = event.payload
                status = payload.get("status", "failed")
                if status == "completed":
                    result_state = TaskState.COMPLETED
                elif status == "cancelled":
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
        _event_bus.unsubscribe(EventType.WATCHDOG_TIMEOUT, _on_watchdog_timeout)
        _event_bus.unsubscribe(EventType.NEED_HUMAN, _on_need_human)
        _event_bus.unsubscribe(EventType.RESUMED, _on_resumed)
        await runner.stop_task()
        _active_runners.pop(task_id, None)
