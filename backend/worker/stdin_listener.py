"""StdinListener —— 从 stdin 读取 Command 并解析

设计要点:
- stdin 按行读取,每行是一个 Command JSON
- 用 asyncio.to_thread 把阻塞的 sys.stdin.readline() 卸载到线程池,
  避免阻塞事件循环,保证 Worker 可被 asyncio.wait_for 中断
- JSON 解析失败时记录日志但不中断循环
"""

from __future__ import annotations

import asyncio
import sys
from typing import Self

import structlog
from pydantic import ValidationError

from app.runtime.protocol.schemas import Command

logger = structlog.get_logger(__name__)


class StdinListener:
    """从 stdin 读取 Runtime 命令

    用法:
        listener = StdinListener()
        async for command in listener:
            ...

    readline() 在线程池执行 → 不阻塞事件循环 → 可用 asyncio.wait_for 设超时
    """

    def __init__(self) -> None:
        self._running = False
        self._stopped = False

    def stop(self) -> None:
        """停止监听(下一个迭代时退出)"""
        self._stopped = True

    def __aiter__(self) -> Self:
        self._running = True
        self._stopped = False
        return self

    async def __anext__(self) -> Command:
        while self._running and not self._stopped:
            try:
                # 在线程池执行阻塞 I/O,不阻塞事件循环
                line = await asyncio.to_thread(sys.stdin.readline)
            except Exception:
                logger.exception("stdin 读取异常, Listener 退出")
                break

            if not line:
                # EOF: 父进程关闭 stdin pipe
                raise StopAsyncIteration

            line_str = line.strip()
            if not line_str:
                continue

            try:
                return Command.model_validate_json(line_str)
            except ValidationError:
                logger.warning("stdin 命令解析失败", line_length=len(line_str))
                continue

        raise StopAsyncIteration
