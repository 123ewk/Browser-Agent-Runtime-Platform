"""任务状态管理器 —— Runtime 唯一真相源

设计要点:
- 每个 task_id 维护当前 TaskState,存储在内存 dict 中(V1 不持久化到 DB)
- transition() 校验合法性后才变更,非法转换抛出 ValueError
- 每次合法变更发布 TASK_STATE_CHANGED 到 EventBus
- 终态不可再转换

模式: Producer(发布状态变更事件),非 Consumer

Rehydrate 设计(2026-06-10 bug 修复):
- 进程启动时从 DB 重建内存状态: 调用 restore_state() 直接写内存(不发布事件)
- 同时启动 watchdog,30s 内没有收到对应任务的 transition 事件,
  主动 force_fail() 标记 FAILED(原因:"后端重启,任务中断")
- 修复"后端重启后 /tasks/{id} 返回 PENDING, 与 DB 实际 status 不一致"的问题
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from uuid import uuid4

import structlog

from app.runtime.event_bus import EventBus
from app.runtime.protocol.schemas import RuntimeEvent, TaskStateChangedPayload
from app.runtime.protocol.transitions import can_transition, is_terminal
from app.runtime.protocol.types import EventType, TaskState

logger = structlog.get_logger(__name__)

# Watchdog 默认超时(秒)—— 进程重启后,30s 内 rehydrated 任务没有任何 transition
# 事件则认为任务已死(Worker 进程不会随 FastAPI 进程自动恢复)
DEFAULT_REHYDRATE_TIMEOUT_S: float = 30.0
# Watchdog 扫描间隔(秒)
WATCHDOG_SCAN_INTERVAL_S: float = 5.0


class InvalidTransitionError(ValueError):
    """状态转换非法异常"""

    def __init__(self, task_id: str, current: TaskState, target: TaskState) -> None:
        super().__init__(f"非法的状态转换: task={task_id}, {current.value} → {target.value}")
        self.task_id = task_id
        self.current = current
        self.target = target


class TaskStateManager:
    """任务状态机 —— 唯一真相源

    用法:
        mgr = TaskStateManager(event_bus)
        await mgr.transition("task-001", TaskState.RUNNING, "用户启动任务")
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._states: dict[str, TaskState] = {}
        # 记录每个 task 的最后变更原因,方便查询
        self._reasons: dict[str, str] = {}
        # V2.5: 任务上下文存储 (如 ASK_HUMAN interrupt_payload 等)
        self._contexts: dict[str, dict[str, dict]] = {}
        # 启动时 rehydrate 进来的任务,等待 watchdog 验证是否"真活着"
        # task_id → restore 时刻(monotonic 时间戳,不受系统时间调整影响)
        self._rehydrated: dict[str, float] = {}
        # 转换表对 PENDING/STOPPING/PAUSED 不允许直接 FAILED,
        # 但 rehydrate/watchdog 是"系统级恢复",应允许绕过。
        # 因此 force_fail() 单独走一条不校验转换表的路径。
        self._rehydrate_timeout_s = DEFAULT_REHYDRATE_TIMEOUT_S
        self._watchdog_task: asyncio.Task[None] | None = None

    async def transition(
        self,
        task_id: str,
        to_state: TaskState,
        reason: str = "",
    ) -> TaskState:
        """执行状态转换

        1. 校验合法性(can_transition)
        2. 更新内存状态
        3. 发布 TASK_STATE_CHANGED 事件到 EventBus

        Raises:
            InvalidTransitionError: 转换非法时抛出
        """
        current = self._states.get(task_id, TaskState.PENDING)

        if not can_transition(current, to_state):
            raise InvalidTransitionError(task_id, current, to_state)

        self._states[task_id] = to_state
        self._reasons[task_id] = reason
        # 正常 transition 视为"任务真活着",从 rehydrated 集合摘除
        self._rehydrated.pop(task_id, None)

        event = RuntimeEvent(
            event_id=_new_event_id(),
            event=EventType.TASK_STATE_CHANGED,
            ts=datetime.now(UTC),
            task_id=task_id,
            payload=TaskStateChangedPayload(
                from_state=current.value,
                to_state=to_state.value,
                reason=reason,
            ).model_dump(),
        )

        logger.info(
            "task.state_transition",
            task_id=task_id,
            from_state=current.value,
            to_state=to_state.value,
            reason=reason,
        )

        await self._event_bus.publish(event)
        return to_state

    async def force_fail(
        self,
        task_id: str,
        reason: str = "系统级恢复:任务中断",
    ) -> TaskState | None:
        """强制 transition 到 FAILED —— 绕过 can_transition 校验。

        用途: 启动 rehydrate 后, watchdog 判定 rehydrated 任务超时无活动时调用。
        适用于 PENDING/STOPPING/PAUSED 等正常转换表不直接允许 FAILED 的状态。

        Returns:
            转换后的 FAILED 状态;若任务已经是终态则返回 None。

        注意: 该方法会发布 TASK_STATE_CHANGED 事件,TimelineRecorder 会同步到 DB。
        """
        current = self._states.get(task_id, TaskState.PENDING)
        if is_terminal(current):
            self._rehydrated.pop(task_id, None)
            return None

        self._states[task_id] = TaskState.FAILED
        self._reasons[task_id] = reason
        self._rehydrated.pop(task_id, None)

        event = RuntimeEvent(
            event_id=_new_event_id(),
            event=EventType.TASK_STATE_CHANGED,
            ts=datetime.now(UTC),
            task_id=task_id,
            payload=TaskStateChangedPayload(
                from_state=current.value,
                to_state=TaskState.FAILED.value,
                reason=reason,
            ).model_dump(),
        )

        logger.warning(
            "task.state_force_failed",
            task_id=task_id,
            from_state=current.value,
            reason=reason,
        )

        await self._event_bus.publish(event)
        return TaskState.FAILED

    def restore_state(
        self,
        task_id: str,
        state: TaskState,
        reason: str = "后端启动 rehydrate",
    ) -> None:
        """直接写内存状态,不发布事件 —— 专供启动 rehydrate 使用。

        与 transition() 的区别:
        - transition() 会发布 TASK_STATE_CHANGED 事件
        - restore_state() 只更新内存(因为 DB 已经是这个状态了,不需要再写一次)
        - 任务会被登记到 _rehydrated,等 watchdog 验证

        Args:
            task_id: 任务 ID
            state: 从 DB 读出的状态
            reason: 写日志/查询时的原因说明
        """
        self._states[task_id] = state
        self._reasons[task_id] = reason
        self._rehydrated[task_id] = time.monotonic()
        logger.info(
            "task.state_restored",
            task_id=task_id,
            state=state.value,
            reason=reason,
        )

    async def start_watchdog(self) -> None:
        """启动 watchdog 后台任务。

        重复调用幂等。
        """
        if self._watchdog_task is not None and not self._watchdog_task.done():
            return
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(),
            name="task-state-watchdog",
        )
        logger.info("task_state.watchdog_started", timeout_s=self._rehydrate_timeout_s)

    async def stop_watchdog(self) -> None:
        """关闭 watchdog 后台任务。"""
        if self._watchdog_task is None:
            return
        self._watchdog_task.cancel()
        try:
            await self._watchdog_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("task_state.watchdog_stop_error")
        finally:
            self._watchdog_task = None
        logger.info("task_state.watchdog_stopped")

    def get_state(self, task_id: str) -> TaskState:
        """获取当前状态,不存在则返回 PENDING"""
        return self._states.get(task_id, TaskState.PENDING)

    def get_reason(self, task_id: str) -> str:
        """获取最后一次状态变更原因"""
        return self._reasons.get(task_id, "")

    def is_terminal(self, task_id: str) -> bool:
        """判断任务是否已结束"""
        return is_terminal(self.get_state(task_id))

    # ── V2.5: 任务上下文存储 (ASK_HUMAN interrupt_payload 等) ──

    def set_context(self, task_id: str, key: str, value: dict) -> None:
        """设置任务级上下文 —— 纯内存, 进程重启丢失 (可接受)"""
        if task_id not in self._contexts:
            self._contexts[task_id] = {}
        self._contexts[task_id][key] = value

    def get_context(self, task_id: str, key: str) -> dict | None:
        """获取任务级上下文"""
        return self._contexts.get(task_id, {}).get(key)

    def clear_context(self, task_id: str) -> None:
        """清除任务的所有上下文 (任务结束时调用)"""
        self._contexts.pop(task_id, None)

    def rehydrated_count(self) -> int:
        """当前等待 watchdog 验证的 rehydrated 任务数(供测试 / 监控用)"""
        return len(self._rehydrated)

    # ── 内部 ──────────────────────────────────────────────

    async def _watchdog_loop(self) -> None:
        """watchdog 主循环 —— 定期扫描 rehydrated 任务,超时则 force_fail。"""
        try:
            while True:
                await asyncio.sleep(WATCHDOG_SCAN_INTERVAL_S)
                await self._sweep_rehydrated()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("task_state.watchdog_loop_crashed")
            # 不要让 watchdog 静默死掉,留个明确的日志供调查
            raise

    async def _sweep_rehydrated(self) -> None:
        """扫描超时未活动的 rehydrated 任务并 force_fail。"""
        now = time.monotonic()
        # 收集再处理(不能在迭代时改 dict)
        to_fail: list[str] = [
            task_id
            for task_id, t0 in self._rehydrated.items()
            if now - t0 >= self._rehydrate_timeout_s
        ]
        if not to_fail:
            return
        for task_id in to_fail:
            try:
                await self.force_fail(
                    task_id, f"后端重启后 {self._rehydrate_timeout_s:.0f}s 内无活动事件"
                )
            except Exception:
                logger.exception("task_state.watchdog_force_fail_failed", task_id=task_id)


def _new_event_id() -> str:
    """生成唯一事件 ID"""
    return f"evt-{uuid4().hex[:12]}"
