"""内存事件总线 —— V1 单进程异步广播

设计要点:
- V1 只做内存总线,不需要 Redis Pub/Sub(单进程即可)
- publish() 使用 asyncio.gather + return_exceptions=True,
  单个 handler 失败不会影响其他 handler
- subscribe() 按事件类型注册 handler,同一个 handler 可以注册多个事件类型
- unsubscribe() 移除注册,用于 cleanup 时避免泄漏

Consumer 清单(订阅关系):
  WebSocketManager   → 所有用户可见事件(转发前端)
  CheckpointManager  → STEP_COMPLETE, TASK_STATE_CHANGED
  ProcessWatchdog    → WORKER_HEARTBEAT, STEP_START, STEP_COMPLETE
  HumanGate          → NEED_CONFIRM
  TimelineRecorder   → STEP_START, STEP_COMPLETE, ERROR, SCREENSHOT, TASK_STATE_CHANGED
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from app.runtime.protocol.types import EventType

from .protocol.schemas import RuntimeEvent

logger = structlog.get_logger(__name__)

# 事件 handler 签名: async (RuntimeEvent) -> None
EventHandler = Callable[[RuntimeEvent], Awaitable[Any]]


class EventBus:
    """V1 内存事件总线

    用法:
        bus = EventBus()
        bus.subscribe(EventType.STEP_COMPLETE, my_handler)
        await bus.publish(event)
    """

    def __init__(self) -> None:
        # defaultdict 避免 subscribe 前需检查 key 存在
        self._handlers: dict[EventType | str, list[EventHandler]] = defaultdict(list)

    def subscribe(
        self,
        event_type: EventType | str,
        handler: EventHandler,
    ) -> None:
        """注册事件 handler

        Args:
            event_type: 事件类型,可以是 EventType 枚举值或字符串(如 "ALL")
            handler: async callable, 接收 RuntimeEvent, 无返回值
        """
        self._handlers[event_type].append(handler)
        logger.debug("eventbus.subscribe", event_type=str(event_type))

    def unsubscribe(
        self,
        event_type: EventType | str,
        handler: EventHandler,
    ) -> None:
        """移除事件 handler —— cleanup 时使用,避免泄漏"""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
            logger.debug("eventbus.unsubscribe", event_type=str(event_type))

    async def publish(self, event: RuntimeEvent) -> None:
        """广播事件到所有注册的 handler

        使用 asyncio.gather 并发调用所有 handler:
        - return_exceptions=True 保证单个 handler 异常不影响其他
        - 异常会被记录到日志,不会向上传播
        """
        handlers = list(self._handlers.get(event.event, []))
        # "ALL" 是一个特殊的通配符订阅,用于 WebSocketManager 等需监听所有事件的消费者
        handlers.extend(self._handlers.get("ALL", []))

        if not handlers:
            return

        logger.debug(
            "eventbus.publish",
            event_id=event.event_id,
            event_type=event.event,
            handler_count=len(handlers),
        )

        results = await asyncio.gather(
            *(handler(event) for handler in handlers),
            return_exceptions=True,
        )

        # 记录异常但不向上传播
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(
                    "eventbus.handler_error",
                    event_type=event.event,
                    handler=handlers[i].__name__,
                    error=str(result),
                )

    def handler_count(self, event_type: EventType | str | None = None) -> int:
        """返回已注册 handler 数量(调试用)"""
        if event_type is not None:
            return len(self._handlers.get(event_type, []))
        return sum(len(h) for h in self._handlers.values())
