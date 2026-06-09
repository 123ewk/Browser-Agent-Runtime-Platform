"""BrowserTaskRunner —— Worker 子进程生命周期管理 + stdin/stdout JSONL 协议

设计要点:
- 使用 asyncio.create_subprocess_exec 启动 Worker 子进程
- 4 个后台协程独立运行,通过 Queue/Event 通信:
  1. _stdin_writer_loop()    — Command Queue → JSON Lines → process.stdin
  2. _stdout_reader_loop()   — process.stdout → JSON Lines → RuntimeEvent → EventBus
  3. _stderr_collector_loop() — process.stderr → 日志文件 + ERROR 事件
  4. _process_monitor_loop() — proc.wait() → 检测异常退出
- WORKER_READY 通过 asyncio.Event 同步(不用 sleep 轮询)
- 三阶段停止: STOP 命令 → wait(5s) → kill(2s)
- sentinel 值(None)用于通知 stdin_writer 退出
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import structlog

from app.runtime.event_bus import EventBus
from app.runtime.protocol.constants import (
    STDIN_QUEUE_MAXSIZE,
    STDOUT_BUFFER_LIMIT,
    WORKER_KILL_TIMEOUT,
    WORKER_READY_TIMEOUT,
    WORKER_STOP_TIMEOUT,
)
from app.runtime.protocol.schemas import (
    Command,
    RuntimeEvent,
    StartPayload,
)
from app.runtime.protocol.types import CommandType, EventType

logger = structlog.get_logger(__name__)


class TaskContext:
    """启动一个 Worker 任务所需的上下文"""

    def __init__(
        self,
        task_id: str,
        goal: str,
        session_id: str = "",
        skill: str = "browser",
        action: dict | None = None,
        storage_state_path: str | None = None,
        max_steps: int = 20,
        timeout_seconds: int = 120,
    ) -> None:
        self.task_id = task_id
        self.goal = goal
        self.session_id = session_id or task_id
        self.skill = skill
        self.action = action  # ActionDetail as dict
        self.storage_state_path = storage_state_path
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds


class WorkerLaunchError(RuntimeError):
    """Worker 启动失败异常"""


class WorkerTimeoutError(RuntimeError):
    """Worker 超时异常"""


class BrowserTaskRunner:
    """管理一个 Worker 子进程的完整生命周期

    用法:
        runner = BrowserTaskRunner(event_bus, worker_module="backend.worker.main")
        await runner.start_task(TaskContext(...))
        await runner.send_command(some_cmd)
        await runner.stop_task()
    """

    def __init__(
        self,
        event_bus: EventBus,
        *,
        worker_module: str = "worker.main",
        worker_cwd: str | None = None,
        stderr_dir: str | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._worker_module = worker_module
        # worker_cwd 默认为 backend/ 目录(Worker 进程的工作目录)
        self._worker_cwd = worker_cwd or str(Path(__file__).resolve().parent.parent.parent)
        self._stderr_dir = Path(stderr_dir) if stderr_dir else Path("logs/worker")

        # 进程状态
        self._process: asyncio.subprocess.Process | None = None
        self._task_id: str | None = None

        # 同步原语
        self._ready_event = asyncio.Event()
        self._command_queue: asyncio.Queue[Command | None] = asyncio.Queue(
            maxsize=STDIN_QUEUE_MAXSIZE
        )

        # 后台协程引用(用于 cleanup)
        self._tasks: list[asyncio.Task] = []

    @property
    def task_id(self) -> str | None:
        """当前任务 ID(只读) —— 供外部日志/调试使用"""
        return self._task_id

    # ═════════════════════════════════════════════════════════════
    # 公共接口
    # ═════════════════════════════════════════════════════════════

    async def start_task(self, context: TaskContext) -> None:
        """启动 Worker 子进程并等待 READY

        步骤:
        1. 启动子进程(asyncio.create_subprocess_exec)
        2. 启动 4 个后台协程
        3. 等待 WORKER_READY 事件(timeout=10s)
        4. 发送 START 命令

        Raises:
            WorkerLaunchError: 子进程启动失败
            WorkerTimeoutError: 等待 WORKER_READY 超时
        """
        if self._process is not None:
            raise WorkerLaunchError("Worker 已在运行,不能重复启动")

        self._task_id = context.task_id
        self._ready_event.clear()

        # 确保 stderr 目录存在
        self._stderr_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 直接用当前解释器启动 Worker 子进程:
            # - 父进程已在 backend/ 目录(via cwd=self._worker_cwd),uv sync 已就绪
            # - 用 sys.executable 而非 "uv run",避免每次 spawn 触发 uv 的 venv 检查/同步开销(可省数秒)
            # - 传绝对模块路径不可行(子进程 sys.path 不同),用 "-m" 让 Python 走 sys.path
            self._process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                self._worker_module,
                "--task-id",
                context.task_id,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._worker_cwd,
            )
        except Exception as e:
            raise WorkerLaunchError(f"Worker 子进程启动失败: {e}") from e

        logger.info(
            "worker.process_started",
            task_id=context.task_id,
            pid=self._process.pid,
        )

        # 启动 4 个后台协程
        self._tasks = [
            asyncio.ensure_future(self._stdin_writer_loop()),
            asyncio.ensure_future(self._stdout_reader_loop()),
            asyncio.ensure_future(self._stderr_collector_loop()),
            asyncio.ensure_future(self._process_monitor_loop()),
        ]

        # 等待 WORKER_READY —— 用 asyncio.Event 而非 sleep 轮询
        try:
            await asyncio.wait_for(
                self._ready_event.wait(),
                timeout=WORKER_READY_TIMEOUT,
            )
        except TimeoutError as err:
            await self.cleanup()
            raise WorkerTimeoutError(f"等待 WORKER_READY 超时({WORKER_READY_TIMEOUT}s)") from err

        # 发送 START 命令 (含 skill + action)
        start_payload = StartPayload(
            session_id=context.session_id,
            goal=context.goal,
            skill=context.skill,
            action=context.action,
            storage_state_path=context.storage_state_path,
            max_steps=context.max_steps,
            timeout_seconds=context.timeout_seconds,
        )
        # action 如果为 None,StartPayload 会序列化为 null,Worker 侧容错
        start_cmd = Command(
            command_id=_new_command_id(),
            type=CommandType.START,
            payload=start_payload.model_dump(exclude_none=True),
        )
        await self.send_command(start_cmd)

        logger.info("worker.task_started", task_id=context.task_id)

    async def send_command(self, cmd: Command) -> None:
        """往 Worker 发送命令(放入 stdin 队列)"""
        try:
            self._command_queue.put_nowait(cmd)
        except asyncio.QueueFull:
            logger.warning(
                "worker.command_queue_full",
                command_id=cmd.command_id,
                command_type=cmd.type,
            )

    async def stop_task(self, timeout: float = WORKER_STOP_TIMEOUT) -> None:
        """三阶段停止

        1. 发 STOP 命令
        2. 等待 Worker 退出(timeout)
        3. 超时则 kill
        """
        if self._process is None:
            return

        logger.info("worker.stopping", task_id=self._task_id)

        # 阶段 1: 发送 STOP 命令
        stop_cmd = Command(
            command_id=_new_command_id(),
            type=CommandType.STOP,
        )
        # send_command 自身不会抛异常(队列满只 warning),此处 suppress 仅作防御
        with contextlib.suppress(Exception):
            await self.send_command(stop_cmd)

        # 阶段 2: 等待退出
        try:
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
            logger.info("worker.stopped_gracefully", task_id=self._task_id)
            return
        except TimeoutError:
            pass

        # 阶段 3: 强制 kill
        logger.warning("worker.killing", task_id=self._task_id)
        try:
            self._process.kill()
            await asyncio.wait_for(self._process.wait(), timeout=WORKER_KILL_TIMEOUT)
        except Exception:
            logger.error("worker.kill_failed", task_id=self._task_id)

    async def cleanup(self) -> None:
        """清理资源:发哨兵 → 取消协程 → 关闭进程"""
        # 发哨兵通知 stdin_writer 退出 —— 队列满说明 stdin_writer 已停,无需处理
        with contextlib.suppress(asyncio.QueueFull):
            self._command_queue.put_nowait(None)  # None = 哨兵

        # 取消所有后台协程
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        # 关闭进程 —— 已经退出/被 kill 的进程再调用 kill/wait 都会抛异常,直接吞掉
        if self._process is not None and self._process.returncode is None:
            with contextlib.suppress(Exception):
                self._process.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._process.wait(), timeout=WORKER_KILL_TIMEOUT)

        self._process = None
        self._task_id = None

    # ═════════════════════════════════════════════════════════════
    # 后台协程
    # ═════════════════════════════════════════════════════════════

    async def _stdin_writer_loop(self) -> None:
        """Command Queue → JSON Lines → process.stdin

        从 _command_queue 消费 Command,序列化为 JSON 后写入 process.stdin。
        遇到 None(sentinel)时退出。
        """
        assert self._process is not None
        assert self._process.stdin is not None

        while True:
            cmd = await self._command_queue.get()
            if cmd is None:  # sentinel: 退出信号
                break

            try:
                line = cmd.model_dump_json() + "\n"
                self._process.stdin.write(line.encode("utf-8"))
                await self._process.stdin.drain()
                logger.debug(
                    "worker.stdin_wrote",
                    command_id=cmd.command_id,
                    command_type=cmd.type,
                )
            except Exception:
                logger.exception(
                    "worker.stdin_write_error",
                    command_id=cmd.command_id,
                )
                break

    async def _stdout_reader_loop(self) -> None:
        """process.stdout → JSON Lines → RuntimeEvent → EventBus

        按行读取 Worker stdout,每行是一个 RuntimeEvent JSON。
        JSON 解析失败时记录错误但不中断循环(单条坏消息不影响后续)。
        """
        assert self._process is not None
        assert self._process.stdout is not None

        while True:
            try:
                line = await self._process.stdout.readline()
            except Exception:
                logger.exception("worker.stdout_read_error")
                break

            if not line:  # EOF: Worker 退出
                logger.info("worker.stdout_eof", task_id=self._task_id)
                break

            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue

            # 长度保护:超过限制的行截断并记录警告
            if len(line_str) > STDOUT_BUFFER_LIMIT:
                logger.warning(
                    "worker.stdout_line_too_long",
                    length=len(line_str),
                )
                line_str = line_str[:STDOUT_BUFFER_LIMIT]

            try:
                event = RuntimeEvent.model_validate_json(line_str)
            except Exception:
                logger.warning(
                    "worker.stdout_bad_json",
                    line=line_str[:200],
                )
                continue

            logger.debug(
                "worker.stdout_event",
                event_id=event.event_id,
                event_type=event.event,
            )

            # WORKER_READY: 设置 Event 通知 start_task()
            if event.event == EventType.WORKER_READY:
                self._ready_event.set()
                # 继续往下走,也发布到 EventBus

            # TASK_FINISHED: 发布后触发 cleanup
            if event.event == EventType.TASK_FINISHED:
                await self._event_bus.publish(event)
                # 异步触发 cleanup(不阻塞当前协程)
                # 保存 task 引用,注册 done_callback 防止异常静默丢失
                cleanup_task = asyncio.ensure_future(self._on_task_finished(event))

                def _log_cleanup_error(t: asyncio.Task) -> None:
                    if t.cancelled():
                        return
                    exc = t.exception()
                    if exc:
                        logger.error(
                            "worker.cleanup_error",
                            task_id=self._task_id,
                            exc_info=exc,
                        )

                cleanup_task.add_done_callback(_log_cleanup_error)
                return

            await self._event_bus.publish(event)

    async def _stderr_collector_loop(self) -> None:
        """process.stderr → 日志文件 + ERROR 事件

        设计要点:
        - stderr 内容写入文件(便于事后排查)
        - 检测到异常关键字时发布 ERROR 事件到 EventBus
        - 使用 asyncio.to_thread 避免同步文件 I/O 阻塞事件循环
        """
        assert self._process is not None
        assert self._process.stderr is not None

        stderr_path = self._stderr_dir / f"worker-{self._task_id or 'unknown'}.log"

        # 在线程池中打开文件,避免阻塞事件循环
        f = await asyncio.to_thread(open, stderr_path, "a", encoding="utf-8")
        try:
            while True:
                try:
                    line = await self._process.stderr.readline()
                except Exception:
                    logger.exception("worker.stderr_read_error")
                    break

                if not line:
                    break

                line_str = line.decode("utf-8", errors="replace")
                # 在线程池中写入+flush,避免阻塞事件循环
                await asyncio.to_thread(f.write, line_str)
                await asyncio.to_thread(f.flush)

                # 检测异常关键字 → 发布 ERROR 事件
                # 用正则精确匹配,避免 "no error" / "error_handler" 等误报
                # 合并两个 if:只有当正则命中且 task_id 已就绪时才发事件
                if _STDERR_ERROR_PATTERN.search(line_str) and self._task_id:
                    event = RuntimeEvent(
                        event_id=_new_event_id(),
                        event=EventType.ERROR,
                        ts=datetime.now(UTC),
                        task_id=self._task_id,
                        payload={
                            "error_type": "WORKER_STDERR",
                            "message": line_str.strip()[:500],
                            "retryable": False,
                        },
                    )
                    await self._event_bus.publish(event)
        finally:
            await asyncio.to_thread(f.close)

    async def _process_monitor_loop(self) -> None:
        """proc.wait() → 检测异常退出

        正常退出时 returncode=0,异常退出(returncode≠0)时发布 ERROR 事件。

        设计说明: proc.wait() 阻塞直到进程退出,这是正确行为 ——
        Worker 进程在执行任务期间应一直存活(Runtime 端 _run_task 循环已有超时兜底)。
        不要在这里加 asyncio.wait_for 超时,会让正常运行中的任务被误杀。
        V2 真正的 Watchdog 应基于 Worker 心跳事件而非 proc.wait()。
        """
        assert self._process is not None

        returncode = await self._process.wait()

        if returncode != 0 and self._task_id:
            event = RuntimeEvent(
                event_id=_new_event_id(),
                event=EventType.ERROR,
                ts=datetime.now(UTC),
                task_id=self._task_id,
                payload={
                    "error_type": "WORKER_CRASHED",
                    "message": f"Worker 进程异常退出,returncode={returncode}",
                    "retryable": False,
                    "details": {"returncode": returncode},
                },
            )
            await self._event_bus.publish(event)

        logger.info(
            "worker.process_exited",
            task_id=self._task_id,
            returncode=returncode,
        )

    async def _on_task_finished(self, event: RuntimeEvent) -> None:
        """TASK_FINISHED 后自动触发 cleanup"""
        # 只记录关键字段,避免 payload 中的中文导致 Windows GBK 控制台编码错误
        payload_status = event.payload.get("status", "unknown")
        payload_steps = event.payload.get("total_steps", 0)
        logger.info(
            "worker.task_finished_cleanup",
            task_id=self._task_id,
            status=payload_status,
            total_steps=payload_steps,
        )
        await self.cleanup()


def _new_command_id() -> str:
    """生成唯一命令 ID"""
    return f"cmd-{uuid4().hex[:12]}"


def _new_event_id() -> str:
    """生成唯一事件 ID"""
    return f"evt-{uuid4().hex[:12]}"


# stderr 异常检测正则 —— 匹配 Python/Node 日志级别的 ERROR/CRITICAL/FATAL 行首,
# 以及 Traceback/Exception 等明确的异常标识,排除 "no error" / "error_handler" 等误报
_STDERR_ERROR_PATTERN = re.compile(
    r"(?:"
    r"^[^a-zA-Z]*ERROR\b"  # 行首 ERROR 级别(允许前面有时间戳等非字母字符)
    r"|^[^a-zA-Z]*CRITICAL\b"  # 行首 CRITICAL 级别
    r"|^[^a-zA-Z]*FATAL\b"  # 行首 FATAL 级别
    r"|^Traceback\b"  # Python 异常回溯
    r"|Exception:"  # 异常类名后冒号
    r")",
    re.IGNORECASE,
)
