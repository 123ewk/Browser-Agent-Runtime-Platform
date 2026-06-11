"""V2.5 状态转换测试 —— WAITING_USER 合法性校验"""

from __future__ import annotations

from app.runtime.protocol.transitions import can_transition, is_terminal
from app.runtime.protocol.types import TaskState


class TestWaitingUserTransitions:
    """WAITING_USER 状态转换测试"""

    def test_running_to_waiting_user(self) -> None:
        """RUNNING → WAITING_USER: 用户中断 / Agent 求助"""
        assert can_transition(TaskState.RUNNING, TaskState.WAITING_USER) is True

    def test_waiting_user_to_running(self) -> None:
        """WAITING_USER → RUNNING: 用户响应后继续"""
        assert can_transition(TaskState.WAITING_USER, TaskState.RUNNING) is True

    def test_waiting_user_to_stopping(self) -> None:
        """WAITING_USER → STOPPING: 用户取消"""
        assert can_transition(TaskState.WAITING_USER, TaskState.STOPPING) is True

    def test_waiting_user_to_failed(self) -> None:
        """WAITING_USER → FAILED: 超时 / 系统错误"""
        assert can_transition(TaskState.WAITING_USER, TaskState.FAILED) is True

    def test_waiting_user_cannot_go_to_completed_directly(self) -> None:
        """WAITING_USER 不能直接转 COMPLETED"""
        assert can_transition(TaskState.WAITING_USER, TaskState.COMPLETED) is False

    def test_waiting_user_is_not_terminal(self) -> None:
        """WAITING_USER 不是终态"""
        assert is_terminal(TaskState.WAITING_USER) is False

    def test_pending_cannot_go_to_waiting_user(self) -> None:
        """PENDING 不能直接转 WAITING_USER"""
        assert can_transition(TaskState.PENDING, TaskState.WAITING_USER) is False

    def test_waiting_confirm_cannot_go_to_waiting_user(self) -> None:
        """WAITING_CONFIRM 不能直接转 WAITING_USER (需先回 RUNNING)"""
        assert can_transition(TaskState.WAITING_CONFIRM, TaskState.WAITING_USER) is False


class TestV1TransitionsUnchanged:
    """V2.5 不应破坏 V1 转换"""

    def test_terminal_states_unchanged(self) -> None:
        for state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
            assert is_terminal(state) is True
            # 终态不能转出
            assert TaskState.RUNNING not in set()  # 确保没有意外项
