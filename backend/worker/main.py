"""Worker CLI 入口

用法:
    python -m worker.main --task-id <task_id>

Runtime 通过 asyncio.create_subprocess_exec 启动此脚本:
    python -m worker.main --task-id task-001

协议:
  - stdout: JSON Lines (RuntimeEvent 流)
  - stdin:  JSON Lines (Command 流)
  - stderr: 日志/异常(被 Runtime 收集到文件)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import traceback

import structlog


def _configure_worker_logging() -> None:
    """Worker 子进程专用日志配置

    与 app.core.logging.configure_logging() 唯一区别:PrintLoggerFactory 写 stderr 而非 stdout
    —— Worker 的 stdout 是 JSON Lines 协议流,日志一旦污染会破坏 Runtime 端 stdout_reader 解析

    不复用 app.core.logging._shared_processors 的原因:
    1. 下划线前缀是"私有",跨包直接 import 违反封装
    2. Worker 的 app/env 元信息通过父进程日志聚合层补,无需在 Worker 内部重复打
    3. Processor 链短一些反而降低子进程启动开销
    """
    level = logging.INFO
    # dev 走彩色 console,prod 走 JSON 方便父进程聚合层 / Loki 消费
    is_dev_tty = sys.stderr.isatty()

    # stdlib logging 兜底走 stderr(Worker 不引 uvicorn/sqlalchemy,但保底)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
        force=True,
    )

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if is_dev_tty:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),  # 关键:写 stderr
        cache_logger_on_first_use=True,
    )


async def main(task_id: str) -> None:
    """Worker 主函数"""
    from worker.worker_session import WorkerSession

    session = WorkerSession(task_id=task_id)
    try:
        await session.run()
    except Exception:
        # 最后的兜底:确保任何未捕获异常都能通过 stderr 被 Runtime 收集
        # 用 logger.critical 而非 print —— 走 structlog 管道,带 level/时间戳
        structlog.get_logger(__name__).critical(
            "Worker 致命错误",
            exc_info=traceback.format_exc(),
        )
        raise


if __name__ == "__main__":
    # 必须先于任何 structlog.get_logger() 调用:否则第一次 logger 用 print 默认到 stdout
    # 污染掉第一批 JSON Lines 事件(虽不大可能,但严格按时间序保证)
    _configure_worker_logging()

    parser = argparse.ArgumentParser(description="Browser Worker")
    parser.add_argument("--task-id", type=str, required=True, help="任务 ID")
    args = parser.parse_args()

    try:
        asyncio.run(main(task_id=args.task_id))
    except Exception:
        sys.exit(1)
