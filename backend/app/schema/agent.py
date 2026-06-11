"""Agent DTO —— API 响应格式,与前端 Agent 类型契约对齐。

V2 引入,字段名/类型稳定,后续 V3 加字段必须保持向后兼容。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, field_validator


class AgentOut(BaseModel):
    """Agent 列表/详情 DTO —— 与前端 Agent 类型完全对齐"""

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
        """把 UUID / 其他可识别类型统一转 str。

        为什么需要:
        - Pydantic v2 对 UUID -> str 不会自动转换,会报 string_type 错
        - service 层从 ORM Agent 构造 AgentOut 时,id 是 uuid.UUID 对象
        - 兜底接收 str 输入,避免重复 str() 调用
        """
        if isinstance(v, uuid.UUID):
            return str(v)
        return str(v)


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
