"""Agent DTO —— API 响应格式,与前端 Agent 类型契约对齐。

V2 引入, V2.5 扩展: +AgentDetailOut / AgentMetricsOut / AgentPauseResumeOut。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, field_validator


class AgentOut(BaseModel):
    """Agent 列表 DTO —— 与前端 Agent 类型完全对齐"""

    id: str  # UUID -> str(自动转换,见下方 validator)
    name: str  # 来源: DB display_name(展示名,非内部 name)
    description: str
    health: str  # healthy / degraded / down
    lastTaskAt: str | None  # ISO 8601,无任务时 null
    successRate24h: float  # 0..1

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v: Any) -> str:
        """把 UUID / 其他可识别类型统一转 str。"""
        if isinstance(v, uuid.UUID):
            return str(v)
        return str(v)


class AgentDetailOut(BaseModel):
    """Agent 详情 DTO (V2.5 新增, GET /agents/{id})"""

    id: str
    name: str
    description: str
    health: str
    lastTaskAt: str | None
    successRate24h: float
    type: str  # browser | data_analysis | ...
    status: str  # active | drained | deprecated
    config: dict | None = None
    totalTasks: int = 0
    avgTokensPerTask: float = 0.0
    avgDurationMs: float = 0.0
    createdAt: str | None = None


class AgentMetricsBucket(BaseModel):
    """时间序列桶 (V2.5 新增)"""

    ts: str  # ISO 8601
    tokens_total: int = 0
    cost_usd: float = 0.0
    step_count: int = 0
    task_count: int = 0
    success_count: int = 0


class AgentMetricsOut(BaseModel):
    """Agent 时间序列指标 (V2.5 新增, GET /agents/{id}/metrics)"""

    agent_id: str
    window: str  # "24h" | "7d" | "30d"
    buckets: list[AgentMetricsBucket] = []
    summary: dict = {}


class AgentPauseResumeOut(BaseModel):
    """Agent 启停响应 (V2.5 新增, POST /agents/{id}/pause|resume)"""

    success: bool
    agent_id: str
    status: str


@dataclass
class AgentMetrics:
    """聚合结果(纯数据,无行为)。

    24h 窗口用于 successRate 展示,1h 窗口用于健康判定。
    所有字段默认为 0,新 agent 无历史任务时用 _EMPTY_METRICS 哨兵。
    """

    success_count_24h: int = 0
    terminal_count_24h: int = 0
    success_count_1h: int = 0
    terminal_count_1h: int = 0
