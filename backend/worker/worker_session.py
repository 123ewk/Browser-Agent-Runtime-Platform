"""WorkerSession —— Worker 主控制器

Phase 2.1: Skill-based 执行 + Trajectory 累积 + 内部执行循环

设计约束 (硬):
- Worker = execution loop owner (deterministic)
- Worker 不判定任务终止 — 只报告 local terminal signal
- Skill = 纯确定性执行,零决策
- Trajectory = append-only,窗口限制

执行流程:
  1. WORKER_READY
  2. 接收 START (含 skill + action)
  3. skill.execute(action) → STEP_COMPLETE (含 trajectory)
  4. 等待 CONTINUE (下一个 action) 或 STOP
  5. 循环直到 STOP → TASK_FINISHED
"""

from __future__ import annotations

import asyncio
import time as _time_module
import traceback
from datetime import UTC, datetime
from uuid import uuid4

import structlog

from app.runtime.protocol.schemas import (
    ActionDetail,
    Command,
    CommandAckPayload,
    ErrorPayload,
    RuntimeEvent,
    ScreenshotPayload,
    StepCompletePayload,
    StepStartPayload,
    TaskFinishedPayload,
)
from app.runtime.protocol.types import CommandType, EventType, TaskResult, WorkerStatus
from app.runtime.trajectory import Trajectory

from .browser_manager import BrowserManager
from .heartbeat_sender import HeartbeatSender
from .skill import BrowserSkill, SkillRegistry
from .stdin_listener import StdinListener
from .stdout_emitter import emit_event

logger = structlog.get_logger(__name__)


class WorkerSession:
    """Worker 主控制器 —— Skill-based 执行引擎

    职责:
    - 管理 Worker 生命周期
    - 接收 Runtime 命令 (START / CONTINUE / STOP)
    - SkillRegistry: 按 skill_name 查找并执行 Skill
    - Trajectory 累积: 每次 STEP_COMPLETE 回传完整轨迹
    - Worker 不判定终止 — Runtime 最终决策
    """

    def __init__(self, task_id: str) -> None:
        self._task_id = task_id
        self._browser: BrowserManager | None = None
        self._registry = SkillRegistry()
        self._trajectory = Trajectory()
        self._step_count = 0
        self._goal = ""
        self._max_steps = 20
        # Worker 当前状态,供心跳上报给 Runtime Watchdog
        self._worker_status = WorkerStatus.IDLE
        # V2.5: INTERRUPT/PAUSE 标志位
        self._interrupt_requested: bool = False  # INTERRUPT: 放弃当前 step
        self._pause_after_step: bool = False  # PAUSE: 完成当前 step 后挂起
        self._step_start_time: float = 0.0  # V2.5: 步骤开始时间 (用于 duration_ms 计算)
        self._heartbeat_sender = HeartbeatSender(
            task_id,
            status_cb=lambda: self._worker_status,
        )

    async def run(self) -> None:
        """Worker 主循环

        1. WORKER_READY
        2. 单 StdinListener 循环: receive → ACK → dispatch
        3. START 后启用 idle timeout(V1 兜底),CONTINUE/STOP 在同一循环内处理
        4. STOP → TASK_FINISHED
        """
        # 在 READY 之前启动心跳发送,确保 Runtime 侧 Watchdog 尽早开始监控
        self._heartbeat_sender.start()

        emit_event(
            RuntimeEvent(
                event_id=_new_event_id(),
                event=EventType.WORKER_READY,
                ts=datetime.now(UTC),
                task_id=self._task_id,
            )
        )

        # 保底超时 —— 防止 Runtime 崩溃后 Worker 僵尸进程
        # 正常流程由 Runtime 端 auto loop 发送 CONTINUE/STOP,
        # 此超时仅在 Runtime 崩溃/网络断开等极端情况下兜底。
        SAFETY_TIMEOUT_SECONDS = 300.0

        listener = StdinListener()
        started = False
        skill_name = "browser"
        try:
            while True:
                # 用 asyncio.wait_for 包装 __anext__,支持 idle timeout
                # START 前不设超时(Worker 等待 Runtime 下发首个命令)
                try:
                    if started:
                        command = await asyncio.wait_for(
                            listener.__anext__(),
                            timeout=SAFETY_TIMEOUT_SECONDS,
                        )
                    else:
                        command = await listener.__anext__()
                except TimeoutError:
                    # 保底超时: Runtime 崩溃或网络断开,Worker 安全退出
                    logger.error(
                        "worker.safety_timeout",
                        task_id=self._task_id,
                        step_count=self._step_count,
                        timeout_seconds=SAFETY_TIMEOUT_SECONDS,
                    )
                    self._emit_finished(
                        TaskResult.FAILED,
                        f"Worker safety timeout — Runtime unresponsive ({self._step_count} steps)",
                        total_steps=self._step_count,
                    )
                    return
                except StopAsyncIteration:
                    # stdin EOF
                    return

                # COMMAND_ACK
                emit_event(
                    RuntimeEvent(
                        event_id=_new_event_id(),
                        event=EventType.COMMAND_ACK,
                        ts=datetime.now(UTC),
                        task_id=self._task_id,
                        payload=CommandAckPayload(
                            command_id=command.command_id,
                        ).model_dump(),
                    )
                )

                if command.type == CommandType.START:
                    await self._handle_start(command)
                    skill_name = command.payload.get("skill", "browser")
                    started = True
                    self._worker_status = WorkerStatus.RUNNING

                elif command.type == CommandType.CONTINUE:
                    if not started:
                        self._emit_error(
                            "NOT_STARTED",
                            "CONTINUE before START",
                            retryable=False,
                        )
                        continue
                    action_data = command.payload.get("action")
                    if action_data:
                        action = ActionDetail(**action_data)
                        await self._execute_action(action, skill_name)
                    else:
                        self._emit_error(
                            "MISSING_ACTION",
                            "CONTINUE command missing action field",
                            retryable=False,
                        )

                elif command.type == CommandType.INTERRUPT:
                    # V2.5: Runtime 请求中断当前动作
                    self._interrupt_requested = True
                    self._worker_status = WorkerStatus.WAITING_USER
                    emit_event(
                        RuntimeEvent(
                            event_id=_new_event_id(),
                            event=EventType.INTERRUPTED,
                            ts=datetime.now(UTC),
                            task_id=self._task_id,
                        )
                    )
                    # 不 break —— 回到循环顶, 等待 RESUME 或 STOP

                elif command.type == CommandType.PAUSE:
                    # V2.5: Runtime 请求完成当前 step 后挂起
                    self._pause_after_step = True
                    self._worker_status = WorkerStatus.WAITING_USER

                elif command.type == CommandType.RESUME:
                    # V2.5: 从 INTERRUPT/PAUSE 恢复
                    self._interrupt_requested = False
                    self._pause_after_step = False
                    self._worker_status = WorkerStatus.RUNNING
                    emit_event(
                        RuntimeEvent(
                            event_id=_new_event_id(),
                            event=EventType.RESUMED,
                            ts=datetime.now(UTC),
                            task_id=self._task_id,
                        )
                    )
                    # Runtime 会在之后发 CONTINUE 带新动作

                elif command.type == CommandType.STOP:
                    await self._handle_stop()
                    return

                # 步数上限检查
                if started and self._step_count >= self._max_steps:
                    self._emit_error(
                        "MAX_STEPS_EXCEEDED",
                        f"Reached max steps ({self._max_steps})",
                        retryable=False,
                    )
                    self._emit_finished(
                        TaskResult.FAILED,
                        f"Max steps exceeded: {self._max_steps}",
                        total_steps=self._step_count,
                    )
                    return

        except Exception:
            logger.critical(
                "worker.internal_error",
                exc_info=traceback.format_exc(),
            )
            self._emit_error(
                "WORKER_INTERNAL",
                traceback.format_exc(),
                retryable=False,
            )
        finally:
            await self._heartbeat_sender.stop()
            listener.stop()

    # ═══════════════════════════════════════════════════════════
    # 命令处理
    # ═══════════════════════════════════════════════════════════

    async def _handle_start(self, command: Command) -> None:
        """处理 START 命令: 初始化 Skill + Browser, 执行第一个 action

        Worker 主循环 run() 在此方法返回后继续处理 CONTINUE/STOP 命令,
        不再进入独立的 _execution_loop(修复双 StdinListener 竞争 stdin 问题)。
        """
        payload = command.payload
        self._goal = payload.get("goal", "")
        skill_name = payload.get("skill", "browser")
        action_data = payload.get("action")
        self._max_steps = payload.get("max_steps", 20)

        if not self._goal:
            self._emit_error("INVALID_GOAL", "goal is empty", retryable=False)
            self._emit_finished(TaskResult.FAILED, "goal is empty")
            return

        try:
            # 启动浏览器
            self._browser = BrowserManager(headless=True)
            await self._browser.start(
                storage_state_path=payload.get("storage_state_path"),
            )
        except Exception as e:
            self._emit_error("BROWSER_LAUNCH_FAILED", str(e), retryable=False)
            self._emit_finished(TaskResult.FAILED, f"Browser launch failed: {e}")
            return

        # 注册 BrowserSkill
        self._registry.register(BrowserSkill(self._browser))

        # 执行第一个 action
        if action_data:
            action = ActionDetail(**action_data)
            await self._execute_action(action, skill_name)

    async def _execute_action(self, action: ActionDetail, skill_name: str) -> None:
        """执行单个动作 —— V2.5: +INTERRUPT/PAUSE 检查 + duration_ms + dom_summary/visible_text

        设计约束: 不做 retry,不做 fallback,不做决策。
        失败时通过 Trajectory 回传 error,Runtime 决定下一步。
        """
        # V2.5: 检查 INTERRUPT/PAUSE 标志 (避免"已自增但被中断" 的序号不一致)
        if self._interrupt_requested or self._pause_after_step:
            return  # Runtime 会重新发 CONTINUE

        # V2.5: NEED_CONFIRM 检查 (在 step_count 自增之前, 避免确认拒绝后多算一步)
        from worker.skill.risk_heuristics import needs_confirm

        should_confirm, confirm_reason = needs_confirm(
            action, self._browser.page.url if self._browser else ""
        )
        if should_confirm:
            emit_event(
                RuntimeEvent(
                    event_id=_new_event_id(),
                    event=EventType.NEED_CONFIRM,
                    ts=datetime.now(UTC),
                    task_id=self._task_id,
                    payload={
                        "action_tag": action.type,
                        "question": f"即将执行高风险操作: {action.description}。原因: {confirm_reason}",
                        "context": {"url": self._browser.page.url if self._browser else ""},
                    },
                )
            )
            self._worker_status = WorkerStatus.WAITING_CONFIRM
            return  # 不执行, 等待 Runtime 发 CONTINUE(approved=True/False)

        self._step_count += 1
        self._step_start_time = _time_module.monotonic()

        # STEP_START
        self._emit_step_start(self._step_count, action.type, action.description)

        # 执行
        result = None
        try:
            skill = self._registry.get(skill_name)
            result = await skill.execute(action)
        except Exception as e:
            result = None
            self._trajectory.add_step(
                action=action,
                summary=f"Skill execution exception: {e}",
                error=str(e),
            )
            self._emit_error(
                "SKILL_EXECUTION_ERROR",
                str(e),
                retryable=True,
                step_index=self._step_count,
            )
            duration_ms = int((_time_module.monotonic() - self._step_start_time) * 1000)
            self._emit_step_complete(
                self._step_count,
                action.type,
                f"Execution error: {e}",
                url=None,
                title=None,
                error=str(e),
                duration_ms=duration_ms,
            )
            return

        # 计算执行耗时
        duration_ms = int((_time_module.monotonic() - self._step_start_time) * 1000)

        # V2.5: INTERRUPT 检查 (在 emit_step_complete 之前)
        if self._interrupt_requested:
            self._emit_step_complete(
                self._step_count,
                action.type,
                "步骤被用户中断",
                url=result.url if result else None,
                title=result.title if result else None,
                duration_ms=duration_ms,
                dom_summary=result.dom_summary if result else "",
                visible_text=result.visible_text if result else "",
                aborted=True,
                abort_reason="user_interrupt",
            )
            return

        # 追加到 Trajectory
        self._trajectory.add_step(
            action=action,
            url=result.url if result else None,
            title=result.title if result else None,
            summary=result.summary if result else "no result",
            error=result.error if result else "unknown error",
        )

        # 截图事件 (如果有)
        if result and result.screenshot_key:
            self._emit_screenshot(result.screenshot_key)

        # STEP_COMPLETE (含 trajectory + V2.5 新字段)
        if result and result.status == "ok":
            self._emit_step_complete(
                self._step_count,
                action.type,
                result.summary,
                url=result.url,
                title=result.title,
                duration_ms=duration_ms,
                dom_summary=result.dom_summary,
                visible_text=result.visible_text,
            )
        else:
            error_msg = result.error if result else "unknown"
            self._emit_error(
                "STEP_FAILED",
                str(error_msg) if error_msg else "unknown",
                retryable=True,
                step_index=self._step_count,
            )
            self._emit_step_complete(
                self._step_count,
                action.type,
                f"Step failed: {error_msg}",
                url=result.url if result else None,
                title=result.title if result else None,
                duration_ms=duration_ms,
                dom_summary=result.dom_summary if result else "",
                visible_text=result.visible_text if result else "",
            )

        # V2.5: PAUSE 检查 (在 emit_step_complete 之后)
        if self._pause_after_step:
            self._worker_status = WorkerStatus.WAITING_USER

    async def _handle_stop(self) -> None:
        """处理 STOP 命令"""
        if self._browser:
            await self._browser.stop()
            self._browser = None
        self._emit_finished(
            TaskResult.CANCELLED, "Task cancelled by user", total_steps=self._step_count
        )

    # ═══════════════════════════════════════════════════════════
    # 事件发射辅助方法
    # ═══════════════════════════════════════════════════════════

    def _emit_step_start(self, index: int, action: str, description: str) -> None:
        emit_event(
            RuntimeEvent(
                event_id=_new_event_id(),
                event=EventType.STEP_START,
                ts=datetime.now(UTC),
                task_id=self._task_id,
                payload=StepStartPayload(
                    index=index,
                    action=action,
                    description=description,
                ).model_dump(),
            )
        )

    def _emit_step_complete(
        self,
        index: int,
        action: str,
        summary: str,
        url: str | None = None,
        title: str | None = None,
        error: str | None = None,
        duration_ms: int | None = None,  # V2.5
        dom_summary: str = "",  # V2.5
        visible_text: str = "",  # V2.5
        aborted: bool = False,  # V2.5
        abort_reason: str = "",  # V2.5
    ) -> None:
        emit_event(
            RuntimeEvent(
                event_id=_new_event_id(),
                event=EventType.STEP_COMPLETE,
                ts=datetime.now(UTC),
                task_id=self._task_id,
                payload=StepCompletePayload(
                    index=index,
                    action=action,
                    summary=summary,
                    url=url,
                    title=title,
                    duration_ms=duration_ms,
                    dom_summary=dom_summary,
                    visible_text=visible_text,
                    aborted=aborted,
                    abort_reason=abort_reason,
                ).model_dump(),
            )
        )

    def _emit_screenshot(self, file_key: str) -> None:
        emit_event(
            RuntimeEvent(
                event_id=_new_event_id(),
                event=EventType.SCREENSHOT,
                ts=datetime.now(UTC),
                task_id=self._task_id,
                payload=ScreenshotPayload(file_key=file_key).model_dump(),
            )
        )

    def _emit_error(
        self,
        error_type: str,
        message: str,
        retryable: bool = False,
        step_index: int | None = None,
    ) -> None:
        emit_event(
            RuntimeEvent(
                event_id=_new_event_id(),
                event=EventType.ERROR,
                ts=datetime.now(UTC),
                task_id=self._task_id,
                payload=ErrorPayload(
                    error_type=error_type,
                    message=message,
                    retryable=retryable,
                    step_index=step_index,
                ).model_dump(),
            )
        )

    def _emit_finished(
        self,
        status: TaskResult,
        summary: str,
        total_steps: int = 0,
    ) -> None:
        emit_event(
            RuntimeEvent(
                event_id=_new_event_id(),
                event=EventType.TASK_FINISHED,
                ts=datetime.now(UTC),
                task_id=self._task_id,
                payload=TaskFinishedPayload(
                    status=status,
                    summary=summary,
                    total_steps=total_steps,
                ).model_dump(),
            )
        )


def _new_event_id() -> str:
    return f"evt-{uuid4().hex[:12]}"
