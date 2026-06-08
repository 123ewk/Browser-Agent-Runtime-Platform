"""任务状态转换规则 —— 合法性校验 + 转换表"""

from __future__ import annotations

from .types import TaskState

# ── 状态转换表 ──
# 终态(COMPLETED / FAILED / CANCELLED)不能转出,不在任何 key 的值中
_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.PENDING: {TaskState.RUNNING},
    TaskState.RUNNING: {
        TaskState.WAITING_CONFIRM,
        TaskState.PAUSED,
        TaskState.STOPPING,
        TaskState.FAILED,
        TaskState.COMPLETED,
    },
    TaskState.WAITING_CONFIRM: {
        TaskState.RUNNING,  # 用户确认后继续
        TaskState.STOPPING,  # 用户在确认期间点了取消
        TaskState.FAILED,
    },
    TaskState.PAUSED: {
        TaskState.RUNNING,
        TaskState.STOPPING,
        TaskState.FAILED,
    },
    TaskState.STOPPING: {TaskState.CANCELLED},
    # 终态:
    # TaskState.COMPLETED: set(),
    # TaskState.FAILED: set(),
    # TaskState.CANCELLED: set(),
}

# ── 终态集合 ──
TERMINAL_STATES: frozenset[TaskState] = frozenset(
    {
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    }
)


def can_transition(current: TaskState, new: TaskState) -> bool:
    """校验状态转换是否合法

    Args:
        current: 当前状态
        new: 目标状态

    Returns:
        True 如果转换合法
    """
    allowed = _TRANSITIONS.get(current, set())
    return new in allowed


def is_terminal(state: TaskState) -> bool:
    """判断是否为终态(不可再转换)"""
    return state in TERMINAL_STATES
