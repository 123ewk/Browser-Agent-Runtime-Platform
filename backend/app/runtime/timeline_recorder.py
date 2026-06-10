"""TimelineRecorder —— 订阅 EventBus,将 Agent 执行轨迹持久化到 PostgreSQL

设计要点:
- 每个事件独立获取 DB session,不持有长连接(避免阻塞连接池)
- 写 DB 失败只记日志,不抛异常(不阻断主流程,保证 Agent 执行不被 DB 拖垮)
- 只在 STEP_COMPLETE / ERROR 时写入完整行(不可变审计日志,不写半成品)
- TASK_STATE_CHANGED 时更新 tasks 表的状态(与内存 TaskStateManager 同步)
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from app.infra.postgres import PostgresClient
from app.repository.task import TaskRepository
from app.repository.task_step import TaskStepRepository
from app.runtime.event_bus import EventBus
from app.runtime.protocol.types import EventType
from app.runtime.task_state import TaskStateManager
from app.schema.task import TaskUpdate

from .protocol.schemas import RuntimeEvent

logger = structlog.get_logger(__name__)

# Task-level 错误(如 Worker 进程崩溃 / 系统超时)写入 task_steps 时使用的 step_index
# 用负数与正常 step(>=0)区分,前端可按 step_index 排序时把它们放最前/最后
TASK_LEVEL_STEP_INDEX: int = -1


class TimelineRecorder:
    """监听 EventBus → 写 task_steps 表 + 同步 tasks 表状态

    订阅的事件:
    - STEP_START: 缓存步骤元信息(供 STEP_COMPLETE 时使用)
    - STEP_COMPLETE: 写入完整步骤行到 task_steps
    - ERROR: 写入错误步骤行到 task_steps(step 级 + task 级都写,2026-06-10 修复)
    - TASK_STATE_CHANGED: 同步任务状态到 tasks 表
    """

    def __init__(
        self,
        event_bus: EventBus,
        pg: PostgresClient,
        task_state_mgr: TaskStateManager,
    ) -> None:
        self._event_bus = event_bus
        self._pg = pg
        self._task_state_mgr = task_state_mgr
        # 缓存 STEP_START 信息(step_index → {action, description, reasoning})
        # keyed by (task_id, step_index)
        self._pending_steps: dict[tuple[str, int], dict[str, Any]] = {}

    async def start(self) -> None:
        self._event_bus.subscribe(EventType.STEP_START, self._on_step_start)
        self._event_bus.subscribe(EventType.STEP_COMPLETE, self._on_step_complete)
        self._event_bus.subscribe(EventType.ERROR, self._on_error)
        self._event_bus.subscribe(EventType.TASK_STATE_CHANGED, self._on_state_changed)
        logger.info("timeline_recorder.started")

    async def stop(self) -> None:
        self._event_bus.unsubscribe(EventType.STEP_START, self._on_step_start)
        self._event_bus.unsubscribe(EventType.STEP_COMPLETE, self._on_step_complete)
        self._event_bus.unsubscribe(EventType.ERROR, self._on_error)
        self._event_bus.unsubscribe(EventType.TASK_STATE_CHANGED, self._on_state_changed)
        logger.info("timeline_recorder.stopped")

    # ── 事件处理 ──────────────────────────────────────────────

    async def _on_step_start(self, event: RuntimeEvent) -> None:
        """缓存 STEP_START 的 action 信息,供后续 STEP_COMPLETE 使用"""
        payload = event.payload
        step_index = payload.get("index")
        if step_index is not None:
            self._pending_steps[(event.task_id, step_index)] = {
                "action": payload.get("action", ""),
                "description": payload.get("description", ""),
                "reasoning": payload.get("reasoning", ""),
            }

    async def _on_step_complete(self, event: RuntimeEvent) -> None:
        """STEP_COMPLETE: 写入完整步骤行"""
        payload = event.payload
        step_index = payload.get("index", 0)
        action = payload.get("action", "")

        # 从缓存取出 STEP_START 时的信息
        pending = self._pending_steps.pop((event.task_id, step_index), {})

        # 构建 result JSONB
        result: dict[str, Any] = {
            "summary": payload.get("summary", ""),
            "url": payload.get("url"),
            "title": payload.get("title"),
            "duration_ms": payload.get("duration_ms"),
            "is_terminal": payload.get("is_terminal", False),
            "description": pending.get("description", ""),
            "reasoning": pending.get("reasoning", ""),
        }

        await self._write_step(
            task_id=event.task_id,
            step_index=step_index,
            action=action,
            result=result,
        )

    async def _on_error(self, event: RuntimeEvent) -> None:
        """ERROR: 写入错误步骤行

        2026-06-10 bug 修复:
        旧实现仅处理 step_index 非空的 step 级 ERROR, 跳过 task 级 ERROR(如
        Worker 进程崩溃 WORKER_CRASHED / 系统 STDERR WORKER_STDERR),
        导致 task_steps 表里看不到崩溃痕迹, 用户调试时无从下手。

        新实现:
        - step 级 ERROR(payload.step_index 非空): 与旧逻辑一致, 写 step_index 行
        - task 级 ERROR(payload.step_index 为空): 用 TASK_LEVEL_STEP_INDEX(-1)
          写一行, action=error_type, result 标记 is_task_level=True
        """
        payload = event.payload
        step_index = payload.get("step_index")
        error_type = payload.get("error_type", "")
        message = payload.get("message", "")

        result: dict[str, Any] = {
            "error": True,
            "error_type": error_type,
            "message": message,
            "retryable": payload.get("retryable", False),
        }

        if step_index is None:
            # Task 级错误: 不绑定具体 step, 用 -1 作为 sentinel
            # 前端按 step_index 排序时会排在 step 0 之前, 视觉上"系统错误置顶"
            result["is_task_level"] = True
            await self._write_step(
                task_id=event.task_id,
                step_index=TASK_LEVEL_STEP_INDEX,
                action=error_type or "TASK_ERROR",
                result=result,
            )
        else:
            await self._write_step(
                task_id=event.task_id,
                step_index=step_index,
                action=error_type,  # 用 error_type 作为 action 标识
                result=result,
            )

    async def _on_state_changed(self, event: RuntimeEvent) -> None:
        """同步任务状态到 tasks 表"""
        payload = event.payload
        to_state = payload.get("to_state")
        if not to_state:
            return

        try:
            task_uuid = uuid.UUID(event.task_id)
        except ValueError:
            return  # task_id 不是 UUID 格式(可能是旧版), 跳过

        session = self._pg.session()
        try:
            repo = TaskRepository(session)
            await repo.update_status(task_uuid, TaskUpdate(status=to_state))
            await session.commit()
        except Exception:
            await session.rollback()
            logger.warning(
                "timeline_recorder.state_sync_failed",
                task_id=event.task_id,
                to_state=to_state,
                exc_info=True,
            )
        finally:
            await session.close()

    # ── 内部辅助 ──────────────────────────────────────────────

    async def _write_step(
        self,
        task_id: str,
        step_index: int,
        action: str,
        result: dict[str, Any],
    ) -> None:
        """写入一条步骤记录到 task_steps 表, 失败不抛异常"""
        try:
            task_uuid = uuid.UUID(task_id)
        except ValueError:
            logger.warning(
                "timeline_recorder.invalid_task_id",
                task_id=task_id,
            )
            return

        session = self._pg.session()
        try:
            repo = TaskStepRepository(session)
            await repo.create(
                task_id=task_uuid,
                step_index=step_index,
                action=action,
                result=result,
            )
            await session.commit()
            logger.debug(
                "timeline_recorder.step_written",
                task_id=task_id,
                step_index=step_index,
                action=action,
            )
        except Exception:
            await session.rollback()
            logger.warning(
                "timeline_recorder.write_failed",
                task_id=task_id,
                step_index=step_index,
                exc_info=True,
            )
        finally:
            await session.close()
