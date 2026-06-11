"""Agent 列表 API —— V2 DB 动态发现 + 真实健康指标

端点:
  GET /agents  — 返回所有 active agent 及其健康/成功率指标

V2: 从 agents 表动态读取,健康指标基于 tasks 表实时聚合。
V1: 硬编码单 agent(已废弃)。
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter

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
