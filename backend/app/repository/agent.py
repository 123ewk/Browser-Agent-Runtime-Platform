"""AgentRepository —— agents 表数据访问。

V2 引入,提供 list_active / get_default / get_by_id 三个查询方法。

为什么这里不返回 DTO(只返回 ORM Agent 对象):
- AgentOut 包含 health / lastTaskAt / successRate24h 三个聚合字段,
  必须在 service 层跨 tasks 表计算,不是 repo 的职责
- repo 强行 model_validate 会让上层拿不到完整 DTO,反而要重做一次
- 严格遵循 api -> service -> repository -> database 分层
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.agent import Agent


class AgentRepository:
    """接收 AsyncSession,返回 ORM Agent 对象,DTO 转换由 service 负责。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self) -> list[Agent]:
        """列出所有 status='active' 的 agent,default 排第一"""
        stmt = (
            select(Agent)
            .where(Agent.status == "active")
            .order_by(Agent.is_default.desc(), Agent.created_at.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return list(rows)

    async def get_default(self) -> Agent | None:
        """获取默认 agent(is_default=True),无则返回 None"""
        stmt = select(Agent).where(Agent.is_default == True)  # noqa: E712
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, agent_id: uuid.UUID) -> Agent | None:
        """按 UUID 查单个 agent"""
        return await self._session.get(Agent, agent_id)

    async def get_display_name_map(self, agent_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """批量获取 agent_id → display_name 映射,避免 N+1"""
        if not agent_ids:
            return {}
        stmt = select(Agent.id, Agent.display_name).where(Agent.id.in_(agent_ids))
        rows = (await self._session.execute(stmt)).all()
        return {row.id: row.display_name for row in rows}
