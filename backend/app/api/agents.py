"""Agent 列表 API —— V2 DB 动态发现 + 真实健康指标

端点:
  GET /agents  — 返回所有 active agent 及其健康/成功率指标

V2: 从 agents 表动态读取,健康指标基于 tasks 表实时聚合。
V1: 硬编码单 agent(已废弃)。
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException

from app.infra.postgres import PostgresClient
from app.repository.agent import AgentRepository
from app.repository.task import TaskRepository
from app.service.agent import AgentService

router = APIRouter(prefix="/agents", tags=["agents"])
log = structlog.get_logger(__name__)


def _get_pg() -> PostgresClient | None:
    """获取 pg client(V1 全局引用模式)"""
    from app.api.tasks import _pg_client

    return _pg_client


@router.get("")
async def list_agents() -> list[dict]:
    """列出当前可用的 Agent 及其健康指标

    V2: 从 DB 动态读取 agents 表,健康指标基于 tasks 表 24h+1h 窗口实时聚合。
    返回字段与 V1 完全兼容(id/name/description/health/lastTaskAt/successRate24h),
    前端零修改。
    """
    pg = _get_pg()
    if pg is None:
        log.warning("agents.pg_not_available")
        return _fallback_response()

    session = pg.session()
    try:
        agent_repo = AgentRepository(session)
        task_repo = TaskRepository(session)
        service = AgentService(agent_repo, task_repo)
        agents = await service.list_active_with_metrics()
        await session.commit()
    except Exception:
        await session.rollback()
        log.warning("agents.query_failed", exc_info=True)
        return _fallback_response()
    finally:
        await session.close()

    if not agents:
        return _fallback_response()

    return [a.model_dump() for a in agents]


def _fallback_response() -> list[dict]:
    """降级响应 —— DB 不可用时返回 V1 兼容的静态 agent

    为什么保留 fallback 而非直接 503:
    - /agents 是 Dashboard 初始化请求,503 会导致整个 Dashboard 白屏
    - 返回 health='down' + lastTaskAt=None 让前端知道后端异常,比全白屏友好
    """
    return [
        {
            "id": "browser-agent-default",
            "name": "Browser Agent",
            "description": "通用浏览器自动化 Agent",
            "health": "down",
            "lastTaskAt": None,
            "successRate24h": 0.0,
        }
    ]


# ── V2.5: Agent 详情 / 指标 / 启停 ──


@router.get("/{agent_id}")
async def get_agent_detail(agent_id: str) -> dict:
    """Agent 详情 —— V2.5 新增

    返回 agent 完整信息 + 聚合指标 (totalTasks/avgTokens/avgDuration)。
    """
    pg = _get_pg()
    if pg is None:
        raise HTTPException(503, "Database not available")

    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "Invalid agent_id format") from None

    session = pg.session()
    try:
        from app.repository.agent import AgentRepository

        agent_repo = AgentRepository(session)
        agent = await agent_repo.get_by_id(aid)
        if agent is None:
            raise HTTPException(404, f"Agent {agent_id} not found")

        # 聚合指标 (从 tasks 表)
        from sqlalchemy import text

        stmt = text(
            """
            SELECT
              COUNT(*) AS total_tasks,
              COALESCE(AVG(total_tokens), 0) AS avg_tokens_per_task,
              COALESCE(AVG(
                (SELECT AVG(duration_ms) FROM task_steps
                 WHERE task_id = tasks.id AND duration_ms IS NOT NULL)
              ), 0) AS avg_duration_ms
            FROM tasks
            WHERE agent_id = :agent_id
            """
        )
        row = (await session.execute(stmt, {"agent_id": aid})).one()
        await session.commit()

        return {
            "id": str(agent.id),
            "name": agent.display_name,
            "description": agent.description,
            "health": "healthy",  # 详情页暂用静态值, 列表页才会算健康指标
            "lastTaskAt": None,
            "successRate24h": 0.0,
            "type": agent.type,
            "status": agent.status,
            "config": agent.config or {},
            "totalTasks": row.total_tasks,
            "avgTokensPerTask": round(float(row.avg_tokens_per_task), 1),
            "avgDurationMs": round(float(row.avg_duration_ms), 1),
            "createdAt": agent.created_at.isoformat() if agent.created_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        log.warning("agent.detail_failed", agent_id=agent_id, exc_info=True)
        raise HTTPException(500, "Failed to get agent detail") from e
    finally:
        await session.close()


@router.get("/{agent_id}/metrics")
async def get_agent_metrics(agent_id: str, window: str = "24h") -> dict:
    """Agent 时间序列指标 —— V2.5 新增

    window: 24h | 7d | 30d
    返回按小时聚合的 token/成本/步骤数。
    """
    pg = _get_pg()
    if pg is None:
        raise HTTPException(503, "Database not available")

    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "Invalid agent_id format") from None

    # 解析窗口
    window_hours = {"24h": 24, "7d": 168, "30d": 720}.get(window, 24)

    session = pg.session()
    try:
        from sqlalchemy import text

        stmt = text(
            """
            WITH hourly AS (
              SELECT
                date_trunc('hour', created_at) AS bucket,
                COUNT(*) AS task_count,
                COUNT(*) FILTER (WHERE status = 'completed') AS success_count,
                COALESCE(SUM(total_tokens), 0) AS tokens_total,
                COALESCE(SUM(total_cost_usd), 0) AS cost_usd
              FROM tasks
              WHERE agent_id = :agent_id
                AND created_at >= NOW() - :window_hours * INTERVAL '1 hour'
              GROUP BY date_trunc('hour', created_at)
              ORDER BY bucket ASC
            ),
            summary AS (
              SELECT
                CASE WHEN COUNT(*) FILTER (WHERE status IN ('completed','failed','cancelled')) > 0
                  THEN COUNT(*) FILTER (WHERE status = 'completed')::float
                       / COUNT(*) FILTER (WHERE status IN ('completed','failed','cancelled'))
                  ELSE 0.0
                END AS success_rate,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(total_cost_usd), 0) AS total_cost
              FROM tasks
              WHERE agent_id = :agent_id
                AND updated_at >= NOW() - :window_hours * INTERVAL '1 hour'
            )
            SELECT * FROM hourly, summary
            """
        )
        rows = (
            (
                await session.execute(
                    stmt,
                    {"agent_id": aid, "window_hours": window_hours},
                )
            )
            .mappings()
            .all()
        )
        await session.commit()

        buckets = [
            {
                "ts": r["bucket"].isoformat() if r["bucket"] else "",
                "tokens_total": int(r["tokens_total"]),
                "cost_usd": float(r["cost_usd"]),
                "step_count": 0,  # task_steps 聚合另做, 先留 0
                "task_count": int(r["task_count"]),
                "success_count": int(r["success_count"]),
            }
            for r in rows
        ]
        summary = {
            "successRate24h": round(float(rows[0]["success_rate"]) if rows else 0, 4),
            "totalTokens": int(rows[0]["total_tokens"]) if rows else 0,
            "totalCostUsd": float(rows[0]["total_cost"]) if rows else 0.0,
        }

        return {
            "agent_id": agent_id,
            "window": window,
            "buckets": buckets,
            "summary": summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        log.warning("agent.metrics_failed", agent_id=agent_id, exc_info=True)
        raise HTTPException(500, "Failed to get agent metrics") from e
    finally:
        await session.close()


@router.post("/{agent_id}/pause")
async def pause_agent(agent_id: str) -> dict:
    """暂停 Agent —— V2.5 新增

    行为: 设置 agent.status='drained', 正在运行的任务继续完成, 新任务拒绝 (409)。
    """
    pg = _get_pg()
    if pg is None:
        raise HTTPException(503, "Database not available")

    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "Invalid agent_id format") from None

    session = pg.session()
    try:
        from app.repository.agent import AgentRepository
        from app.runtime.protocol.types import AgentStatus

        agent_repo = AgentRepository(session)
        agent = await agent_repo.get_by_id(aid)
        if agent is None:
            raise HTTPException(404, f"Agent {agent_id} not found")

        if agent.status == AgentStatus.DRAINED.value:
            return {
                "success": False,
                "agent_id": agent_id,
                "status": "drained",
                "reason": "Agent already drained",
            }

        agent.status = AgentStatus.DRAINED.value
        await session.commit()

        # 失效该 agent 的指标缓存
        _invalidate_agent_cache(aid)

        return {"success": True, "agent_id": agent_id, "status": "drained"}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        log.warning("agent.pause_failed", agent_id=agent_id, exc_info=True)
        raise HTTPException(500, "Failed to pause agent") from e
    finally:
        await session.close()


@router.post("/{agent_id}/resume")
async def resume_agent(agent_id: str) -> dict:
    """恢复 Agent —— V2.5 新增

    行为: 设置 agent.status='active', 恢复接收新任务。
    """
    pg = _get_pg()
    if pg is None:
        raise HTTPException(503, "Database not available")

    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "Invalid agent_id format") from None

    session = pg.session()
    try:
        from app.repository.agent import AgentRepository
        from app.runtime.protocol.types import AgentStatus

        agent_repo = AgentRepository(session)
        agent = await agent_repo.get_by_id(aid)
        if agent is None:
            raise HTTPException(404, f"Agent {agent_id} not found")

        if agent.status == AgentStatus.ACTIVE.value:
            return {
                "success": False,
                "agent_id": agent_id,
                "status": "active",
                "reason": "Agent already active",
            }

        agent.status = AgentStatus.ACTIVE.value
        await session.commit()

        # 失效该 agent 的指标缓存
        _invalidate_agent_cache(aid)

        return {"success": True, "agent_id": agent_id, "status": "active"}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        log.warning("agent.resume_failed", agent_id=agent_id, exc_info=True)
        raise HTTPException(500, "Failed to resume agent") from e
    finally:
        await session.close()


def _invalidate_agent_cache(agent_id: UUID) -> None:
    """失效 agent 指标缓存 (V1 占位, V2 接入 DI 后启用 Redis)

    当前为 no-op: 每次 pause/resume 创建新 Redis client 会导致连接泄漏。
    60s TTL 到期后 Dashboard 下次轮询自动刷新, 不阻塞 pause/resume 主流程。
    V2 通过 DI 注入 RedisClient 后在此处实现主动失效。
    """
    log.debug("_invalidate_agent_cache.noop", agent_id=str(agent_id))
