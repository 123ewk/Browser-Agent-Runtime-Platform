"""AgentService —— Agent 业务逻辑层。

职责:
- 跨表聚合(agents JOIN tasks)
- 健康状态计算(healthy/degraded/down)
- 成功率计算(24h 窗口)

V2 引入。V1 简单场景 tasks/stats 直接调 repository,Agent 涉及跨表聚合+业务规则,
所以引入 service 层。任务/统计的 service 层拆解放到 Phase 8 统一处理。
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from app.core.config import Settings, settings
from app.repository.agent import AgentRepository
from app.repository.task import TaskRepository
from app.schema.agent import AgentMetrics, AgentOut

logger = structlog.get_logger(__name__)


class AgentHealth:
    """健康状态枚举 —— 与前端 AgentHealth 类型对齐"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


# 零值哨兵:新 agent 无历史任务时使用,保证不抛 KeyError
_EMPTY_METRICS = AgentMetrics()


class AgentService:
    """Agent 业务逻辑 —— 跨 agents + tasks 聚合 + 健康计算"""

    def __init__(
        self,
        agent_repo: AgentRepository,
        task_repo: TaskRepository,
        config: Settings | None = None,
    ) -> None:
        self._agent_repo = agent_repo
        self._task_repo = task_repo
        self._settings = config or settings

    async def list_active_with_metrics(self) -> list[AgentOut]:
        """列出所有 active agent 并附带实时健康指标

        DB 查询: 3 次 SQL(O(1) 不随 agent 数量增长)。
        降级策略: DB 异常向上抛,由 api 层统一处理。
        """
        agents = await self._agent_repo.list_active()
        if not agents:
            return []

        # ORM Agent.id 已经是 uuid.UUID,直接用,不要再包 uuid.UUID()
        agent_ids = [a.id for a in agents]
        last_task_map = await self._task_repo.last_task_at_map(agent_ids)
        metrics_map = await self._task_repo.aggregate_metrics(agent_ids)

        result: list[AgentOut] = []
        for agent in agents:
            metrics = metrics_map.get(agent.id, _EMPTY_METRICS)
            last_task_at = last_task_map.get(agent.id)
            health = _compute_health(metrics, last_task_at, self._settings)
            result.append(
                AgentOut(
                    id=agent.id,  # 已是 UUID,AgentOut._coerce_id 会转 str
                    name=agent.display_name,  # 用 display_name 对齐前端契约
                    description=agent.description,
                    health=health,
                    lastTaskAt=last_task_at.isoformat() if last_task_at else None,
                    successRate24h=_compute_success_rate(metrics),
                )
            )
        return result


def _compute_health(
    metrics: AgentMetrics,
    last_task_at: datetime | None,
    config: Settings,
) -> str:
    """健康状态计算规则(按优先级依次判定,命中即返回)

    1. 无历史任务 → healthy(新 agent,避免误判 down)
    2. 超过 inactive_days 无任务 → down
    3. 1h 内有任务:
       a. 1h 失败率 ≥ down 阈值 → down
       b. 1h 失败率 > 0(但 < down 阈值) → degraded
       c. 1h 全成功 → healthy
    4. 1h 内无任务(但 ≤ inactive_days):
       a. 24h 失败率 ≥ degraded 阈值 → degraded
       b. 否则 → healthy(agent 空闲,无近期任务)
    """
    # 规则 1: 新 agent 无任何历史任务
    if last_task_at is None:
        return AgentHealth.HEALTHY

    now = datetime.now(UTC)
    seconds_since_last = (now - last_task_at).total_seconds()
    inactive_seconds = config.agent_health_inactive_days * 86400

    # 规则 2: 长期不活跃
    if seconds_since_last > inactive_seconds:
        return AgentHealth.DOWN

    # 规则 3: 1h 窗口判定(最近 1h 有终态任务)
    if metrics.terminal_count_1h > 0:
        failure_rate_1h = 1.0 - (metrics.success_count_1h / metrics.terminal_count_1h)
        if failure_rate_1h >= config.agent_health_down_failure_rate:
            return AgentHealth.DOWN
        if failure_rate_1h > 0:
            return AgentHealth.DEGRADED
        return AgentHealth.HEALTHY

    # 规则 4: 1h 内无任务,看 24h 窗口
    if metrics.terminal_count_24h > 0:
        failure_rate_24h = 1.0 - (metrics.success_count_24h / metrics.terminal_count_24h)
        if failure_rate_24h >= config.agent_health_degraded_failure_rate:
            return AgentHealth.DEGRADED

    # 规则 4b: agent 空闲(24h 内无失败,或完全无任务)
    return AgentHealth.HEALTHY


def _compute_success_rate(metrics: AgentMetrics) -> float:
    """24h 窗口成功率 —— 无终态任务返回 0.0"""
    if metrics.terminal_count_24h == 0:
        return 0.0
    return round(metrics.success_count_24h / metrics.terminal_count_24h, 4)
