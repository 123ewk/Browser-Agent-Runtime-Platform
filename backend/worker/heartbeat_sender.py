"""HeartbeatSender —— Worker 侧心跳发送器

职责:
  周期发送 WORKER_HEARTBEAT 到 stdout,让 Runtime 侧 ProcessWatchdog 感知 Worker 存活。

生命周期:
  start() → asyncio.create_task(_run()) → stop() → task.cancel()

设计要点:
  - 通过 stdout emit_event() 发送,与 Worker 其他事件共享同一通道
  - 自维护单调递增 seq,Watchdog 据此检测丢包/跳号
  - 异步协程实现,不阻塞 Worker 主循环
  - 异常自动记录但不崩溃(emit_event 失败通常意味着 stdout 已关闭)
  - start/stop 幂等,重复调用不产生多个后台协程
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import structlog

from app.runtime.protocol.constants import WORKER_HEARTBEAT_INTERVAL
from app.runtime.protocol.schemas import RuntimeEvent
from app.runtime.protocol.types import EventType, WorkerStatus

from .stdout_emitter import emit_event

logger = structlog.get_logger(__name__)


class HeartbeatSender:
    """Worker 心跳发送器

    用法:
        sender = HeartbeatSender(task_id, status_cb=lambda: WorkerStatus.RUNNING)
        sender.start()
        ...
        sender.stop()
    """

    def __init__(
        self,
        task_id: str,
        *,
        interval: float = WORKER_HEARTBEAT_INTERVAL,
        status_cb: Callable[[], WorkerStatus] | None = None,
    ) -> None:
        self._task_id = task_id
        self._interval = interval
        self._status_cb = status_cb or (lambda: WorkerStatus.RUNNING)
        self._task: asyncio.Task[None] | None = None
        self._seq: int = 0

    def start(self) -> None:
        """启动心跳发送后台协程(幂等,重复调用不会创建多个协程)"""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._run(),
            name=f"heartbeat-{self._task_id[:12]}",
        )
        logger.debug(
            "heartbeat_sender.started",
            task_id=self._task_id,
            interval=self._interval,
        )

    async def stop(self) -> None:
        """停止心跳发送(幂等,重复调用安全)"""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("heartbeat_sender.stop_error", task_id=self._task_id)
        finally:
            self._task = None
        logger.debug("heartbeat_sender.stopped", task_id=self._task_id)

    async def _run(self) -> None:
        """后台循环: 每 interval 秒发送一次 WORKER_HEARTBEAT

        连续异常超过阈值后退出循环(emit_event 反复失败意味着 stdout 已关闭,
        Worker 继续运行无意义,让外层 WorkerSession 的 safety timeout 兜底退出)。
        """
        max_consecutive_errors = 3
        consecutive_errors = 0
        while True:
            try:
                self._seq += 1
                status = self._status_cb()
                event = RuntimeEvent(
                    event_id=f"evt-{uuid4().hex[:12]}",
                    event=EventType.WORKER_HEARTBEAT,
                    ts=datetime.now(UTC),
                    task_id=self._task_id,
                    payload={
                        "seq": self._seq,
                        "status": status.value,
                        "pid": os.getpid(),
                    },
                )
                emit_event(event)
                consecutive_errors = 0  # 发送成功,重置计数
            except asyncio.CancelledError:
                raise
            except Exception:
                consecutive_errors += 1
                logger.warning(
                    "heartbeat_sender.error",
                    task_id=self._task_id,
                    consecutive_errors=consecutive_errors,
                    exc_info=True,
                )
                if consecutive_errors >= max_consecutive_errors:
                    # 连续失败超过阈值: stdout 大概率已关闭,退出循环让 Worker 自行终止
                    logger.critical(
                        "heartbeat_sender.consecutive_failures_exceeded",
                        task_id=self._task_id,
                        max_errors=max_consecutive_errors,
                    )
                    return
            await asyncio.sleep(self._interval)
