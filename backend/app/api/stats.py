"""Dashboard 统计 API —— V1 最小可用版本

端点:
  GET /stats/dashboard?window=24h  — Dashboard 顶部统计卡片

V1 限制:
- tokens / cost 字段返回 0(tracking 未实现)
- deltaPct 字段返回 0(无历史基线)
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query

from app.core.deps import get_current_user_id
from app.infra.postgres import PostgresClient

router = APIRouter(prefix="/stats", tags=["stats"])
log = structlog.get_logger(__name__)


def _get_pg() -> PostgresClient | None:
    """获取 pg client(V1 全局引用)"""
    from app.api.tasks import _pg_client

    return _pg_client


@router.get("/dashboard")
async def get_dashboard_stats(
    window: str = Query("24h", pattern=r"^(1h|24h|7d|30d)$"),
    user_id: UUID = Depends(get_current_user_id),
) -> dict:
    """Dashboard 顶部统计聚合

    V1: 从 DB 统计 tasksToday / running / successRate,
    tokens/cost 返回 0(后续 Phase 2 实现 token tracking)。
    """
    pg = _get_pg()
    tasks_today = 0
    success_rate = 0.0

    if pg is not None:
        from app.repository.task import TaskRepository

        session = pg.session()
        try:
            repo = TaskRepository(session)
            result = await repo.list_by_user(user_id, limit=1000, offset=0)
            now_ts = datetime.now(UTC)
            # 计算 tasksToday (最近 24h)
            for t in result.items:
                delta = now_ts - t.created_at
                if delta.total_seconds() < 86400:
                    tasks_today += 1
            # 计算 successRate (非 pending/running 中成功的比例)
            terminal = [t for t in result.items if t.status in ("completed", "failed", "cancelled")]
            if terminal:
                success_count = sum(1 for t in terminal if t.status == "completed")
                success_rate = success_count / len(terminal)
            await session.commit()
        except Exception:
            await session.rollback()
            log.warning("stats.query_failed", exc_info=True)
        finally:
            await session.close()

    # running 从内存 TaskStateManager 获取
    from app.api.tasks import get_task_state_manager

    mgr = get_task_state_manager()
    # TaskStateManager 没有 list_all, 用简单方式: 遍历 _active_runners
    from app.api.tasks import _active_runners

    running = sum(1 for task_id in _active_runners if mgr.get_state(task_id).value == "running")

    return {
        "window": window,
        "tasksToday": tasks_today,
        "tasksTodayDeltaPct": 0,
        "running": running,
        "successRate": round(success_rate, 4),
        "tokensToday": 0,
        "tokensTodayDeltaPct": 0,
        "costTodayUsd": 0,
        "estimatedMonthlyCostUsd": 0,
        "agents": [],
    }
