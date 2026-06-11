"""Dashboard 统计 API —— V2.5 SQL 聚合替代 Python 过滤

端点:
  GET /stats/dashboard?window=24h  — Dashboard 顶部统计卡片

V2.5 改进:
- 使用参数化 SQL COUNT(*) FILTER 替代 Python 过滤
- tokens/cost 从 tasks 表直接聚合 (不再硬编码 0)
- 一次查询返回所有卡片数据
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.core.deps import get_current_user_id
from app.infra.postgres import PostgresClient

router = APIRouter(prefix="/stats", tags=["stats"])
log = structlog.get_logger(__name__)

# 窗口映射
_WINDOW_HOURS: dict[str, int] = {"1h": 1, "24h": 24, "7d": 168, "30d": 720}


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

    V2.5: SQL 聚合一次查询返回所有卡片数据。
    window_start 参数化避免计划缓存失效。
    """
    pg = _get_pg()
    window_hours = _WINDOW_HOURS.get(window, 24)
    window_start = datetime.now(UTC) - timedelta(hours=window_hours)

    tasks_today = 0
    success_rate = 0.0
    tokens_today = 0
    cost_today = 0.0

    if pg is not None:
        session = pg.session()
        try:
            stmt = text(
                """
                SELECT
                  COUNT(*) FILTER (WHERE created_at >= :window_start) AS tasks_today,
                  COUNT(*) FILTER (WHERE status IN ('completed','failed','cancelled')
                    AND updated_at >= :window_start) AS terminal_count,
                  COUNT(*) FILTER (WHERE status = 'completed'
                    AND updated_at >= :window_start) AS success_count,
                  COALESCE(SUM(total_tokens) FILTER (WHERE created_at >= :window_start), 0) AS tokens_today,
                  COALESCE(SUM(total_cost_usd) FILTER (WHERE created_at >= :window_start), 0) AS cost_today
                FROM tasks
                WHERE user_id = :user_id
                """
            )
            row = (
                await session.execute(
                    stmt,
                    {"user_id": user_id, "window_start": window_start},
                )
            ).one()
            await session.commit()

            tasks_today = int(row.tasks_today)
            terminal = int(row.terminal_count)
            if terminal > 0:
                success_rate = int(row.success_count) / terminal
            tokens_today = int(row.tokens_today)
            cost_today = float(row.cost_today)
        except Exception:
            await session.rollback()
            log.warning("stats.query_failed", exc_info=True)
        finally:
            await session.close()

    # running 从内存获取
    from app.api.tasks import _active_runners, get_task_state_manager

    mgr = get_task_state_manager()
    running = sum(1 for task_id in _active_runners if mgr.get_state(task_id).value == "running")

    return {
        "window": window,
        "tasksToday": tasks_today,
        "tasksTodayDeltaPct": 0,
        "running": running,
        "successRate": round(success_rate, 4),
        "tokensToday": tokens_today,
        "tokensTodayDeltaPct": 0,
        "costTodayUsd": cost_today,
        "estimatedMonthlyCostUsd": 0,
        "agents": [],
    }
