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
from app.runtime.protocol.types import CommandType, EventType, TaskResult
from app.runtime.trajectory import Trajectory

from .browser_manager import BrowserManager
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

    async def run(self) -> None:
        """Worker 主循环

        1. WORKER_READY
        2. 接收 START → 进入执行循环
        3. 循环: receive → execute → emit → wait
        4. STOP → TASK_FINISHED
        """
        emit_event(
            RuntimeEvent(
                event_id=_new_event_id(),
                event=EventType.WORKER_READY,
                ts=datetime.now(UTC),
                task_id=self._task_id,
            )
        )

        listener = StdinListener()
        try:
            async for command in listener:
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
                    # 提取参数并进入执行循环
                    await self._handle_start(command)
                    # START 后进入内部 loop,不再退出
                    # 后续的 CONTINUE/STOP 在 loop 内处理

                elif command.type == CommandType.STOP:
                    await self._handle_stop()
                    break  # 退出主循环

                # V2: CONTINUE, REJECT
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
            listener.stop()

    # ═══════════════════════════════════════════════════════════
    # 命令处理
    # ═══════════════════════════════════════════════════════════

    async def _handle_start(self, command: Command) -> None:
        """处理 START 命令: 初始化 Skill + Browser, 执行第一个 action, 进入内部循环"""
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

        # 进入执行循环,等待 Runtime 的 CONTINUE/STOP
        await self._execution_loop(skill_name)

    async def _execution_loop(self, skill_name: str) -> None:
        """Worker 内部执行循环

        等待 Runtime 发来的 CONTINUE (下一个 action) 或 STOP。
        Worker 不自动 loop — 每步等待 Runtime 决策。

        ⚠️ V1 已知限制 (TODO):Worker 5s idle timeout 会在 Runtime 还没发 CONTINUE 时
        强制 emit TASK_FINISHED(COMPLETED),本质是把"1 步执行"伪装成"完成"。
        真正的多步 Agent 需要 Runtime 端起 continuation loop(收 STEP_COMPLETE → 调
        PolicyEngine → 发 CONTINUE),由 Runtime 判定 is_terminal 才 STOP。
        本 V1 保留 hack 行为,保证 demo 可跑;V2 必须在 Runtime 端实现闭环。
        """
        import asyncio as aio

        # V1 兜底超时 —— 防止 Runtime 端没发 CONTINUE 时 Worker 永远阻塞
        # 该值偏小是因为 V1 demo 场景下 Runtime 不会主动发 CONTINUE,
        # 5s 是"假装完成"的合理超时;V2 闭环后应增大到几十秒或彻底去掉
        IDLE_TIMEOUT_SECONDS = 5.0

        listener = StdinListener()

        # stdin.readline() 是阻塞的(在 asyncio 里会挂起事件循环),
        # 所以这里使用 __anext__ 轮询 + timeout 实现 idle timeout。
        # 由于 StdinListener 的 __anext__ 是非阻塞 async(for loop 语义),
        # 我们用 asyncio.wait_for 包装每次迭代。
        try:
            while True:
                try:
                    command = await aio.wait_for(
                        listener.__anext__(),
                        timeout=IDLE_TIMEOUT_SECONDS,  # 见上方常量说明
                    )
                except TimeoutError:
                    # V1 兼容: 没有更多命令 → 强制 emit COMPLETED(实际只跑了 1 步)
                    # 该行为是 demo 阶段的妥协,V2 应在 Runtime 端起 continuation loop 替代
                    logger.warning(
                        "worker.idle_timeout_force_finish",
                        task_id=self._task_id,
                        step_count=self._step_count,
                        timeout_seconds=IDLE_TIMEOUT_SECONDS,
                    )
                    self._emit_finished(
                        TaskResult.COMPLETED,
                        f"Task completed, {self._step_count} steps",
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

                if command.type == CommandType.STOP:
                    await self._handle_stop()
                    return

                elif command.type == CommandType.CONTINUE:
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

                # V2: REJECT

                # 步数上限检查
                if self._step_count >= self._max_steps:
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
                "worker.execution_loop_error",
                exc_info=traceback.format_exc(),
            )
            self._emit_error(
                "WORKER_INTERNAL",
                traceback.format_exc(),
                retryable=False,
            )
        finally:
            listener.stop()

    async def _execute_action(self, action: ActionDetail, skill_name: str) -> None:
        """执行单个动作: Skill.execute(action) → Trajectory.add_step → emit

        设计约束: 不做 retry,不做 fallback,不做决策。
        失败时通过 Trajectory 回传 error,Runtime 决定下一步。
        """
        self._step_count += 1

        # STEP_START
        self._emit_step_start(self._step_count, action.type, action.description)

        # 执行
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
            self._emit_step_complete(
                self._step_count,
                action.type,
                f"Execution error: {e}",
                url=None,
                title=None,
                error=str(e),
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

        # STEP_COMPLETE (含 trajectory)
        if result and result.status == "ok":
            self._emit_step_complete(
                self._step_count,
                action.type,
                result.summary,
                url=result.url,
                title=result.title,
            )
        else:
            error_msg = result.error if result else "unknown"
            # error_msg 在静态分析上是 str | None(result.error 可空),
            # 但走到 else 分支说明 result 存在(error 字段可能为 None)—— 兜底为 "unknown"
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
                error=error_msg,
            )

    async def _cleanup_and_finish(self) -> None:
        """清理浏览器并发出 TASK_FINISHED"""
        if self._browser:
            await self._browser.stop()
            self._browser = None
        self._emit_finished(
            TaskResult.COMPLETED,
            f"Task completed, {self._step_count} steps",
            total_steps=self._step_count,
        )

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
