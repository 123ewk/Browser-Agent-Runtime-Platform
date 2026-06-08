"""任务状态管理器 —— Runtime 唯一真相源

设计要点:
- 每个 task_id 维护当前 TaskState,存储在内存 dict 中(V1 不持久化到 DB)
- transition() 校验合法性后才变更,非法转换抛出 ValueError
- 每次合法变更发布 TASK_STATE_CHANGED 到 EventBus
- 终态不可再转换

模式: Producer(发布状态变更事件),非 Consumer
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import structlog

from app.runtime.event_bus import EventBus
from app.runtime.protocol.schemas import RuntimeEvent, TaskStateChangedPayload
from app.runtime.protocol.transitions import can_transition, is_terminal
from app.runtime.protocol.types import EventType, TaskState

logger = structlog.get_logger(__name__)


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

    def get_state(self, task_id: str) -> TaskState:
        """获取当前状态,不存在则返回 PENDING"""
        return self._states.get(task_id, TaskState.PENDING)

    def get_reason(self, task_id: str) -> str:
        """获取最后一次状态变更原因"""
        return self._reasons.get(task_id, "")

    def is_terminal(self, task_id: str) -> bool:
        """判断任务是否已结束"""
        return is_terminal(self.get_state(task_id))


def _new_event_id() -> str:
    """生成唯一事件 ID"""
    return f"evt-{uuid4().hex[:12]}"
