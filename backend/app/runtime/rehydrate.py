"""启动时 rehydrate —— 从 DB 恢复 TaskStateManager 内存状态。

为什么需要:
- TaskStateManager 内存状态在进程重启后清空(纯内存 dict)
- 不重建会导致 /tasks/{id} 接口返回 PENDING(默认值),与 DB 实际 status 不一致
- 前端基于这个错误 status 走"非终态 = 在跑"判定 → 输入框被锁

设计:
1. 扫描 DB 中所有非终态任务,恢复到 TaskStateManager(只写内存,不发布事件)
2. 启动 TaskStateManager 内的 watchdog,30s 内 rehydrated 任务若没有任何 transition
   事件则 force_fail() (Worker 进程不会随 FastAPI 进程自动恢复)
"""

from __future__ import annotations

import structlog
from sqlalchemy import select

from app.infra.postgres import PostgresClient
from app.model import Task
from app.runtime.protocol.types import TaskState
from app.runtime.task_state import TaskStateManager

logger = structlog.get_logger(__name__)

# 非终态集合 —— 与 TaskState 枚举值对齐
# (PENDING/RUNNING/WAITING_CONFIRM/PAUSED/STOPPING)
_NON_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        TaskState.PENDING.value,
        TaskState.RUNNING.value,
        TaskState.WAITING_CONFIRM.value,
        TaskState.PAUSED.value,
        TaskState.STOPPING.value,
    }
)


async def rehydrate_task_states(
    pg: PostgresClient,
    state_mgr: TaskStateManager,
) -> int:
    """从 DB 扫描非终态任务,恢复到 TaskStateManager 内存。

    Args:
        pg: Postgres 客户端(可为 None, 此时直接返回 0)
        state_mgr: 目标状态管理器

    Returns:
        成功 rehydrate 的任务数。pg 不可用 / 查询失败时返回 0。
    """
    if pg is None:
        logger.warning("rehydrate.skipped", reason="pg_client_none")
        return 0

    session = pg.session()
    try:
        stmt = select(Task.id, Task.status).where(Task.status.in_(_NON_TERMINAL_STATUSES))
        rows = (await session.execute(stmt)).all()
    except Exception:
        await session.rollback()
        logger.exception("rehydrate.query_failed")
        return 0
    finally:
        await session.close()

    if not rows:
        logger.info("rehydrate.complete", count=0)
        return 0

    restored = 0
    invalid = 0
    for row in rows:
        task_id_str = str(row.id)
        db_status = row.status
        try:
            state = TaskState(db_status)
        except ValueError:
            # 非法 status(CHECK 约束上线后理论上不会发生,保留防御)
            invalid += 1
            logger.warning(
                "rehydrate.invalid_status",
                task_id=task_id_str,
                db_status=db_status,
            )
            # 保守地按 PENDING 处理 —— watchdog 会在 30s 后 force_fail
            state = TaskState.PENDING
        state_mgr.restore_state(task_id_str, state, "后端启动 rehydrate")
        restored += 1

    logger.info(
        "rehydrate.complete",
        restored=restored,
        invalid_status=invalid,
    )
    return restored
