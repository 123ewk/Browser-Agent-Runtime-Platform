"""CheckpointRepository —— Agent 状态保存与恢复。"""

from __future__ import annotations

import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model import Checkpoint
from app.schema.checkpoint import CheckpointOut


class CheckpointRepository:
    """Checkpoint 数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task_id: uuid.UUID, state_data: dict) -> CheckpointOut:
        cp = Checkpoint(task_id=task_id, state_data=state_data)
        self._session.add(cp)
        await self._session.flush()
        return CheckpointOut.model_validate(cp)

    async def get_latest_by_task(self, task_id: uuid.UUID) -> CheckpointOut | None:
        result = await self._session.execute(
            select(Checkpoint)
            .where(Checkpoint.task_id == task_id)
            .order_by(desc(Checkpoint.created_at))
            .limit(1)
        )
        cp = result.scalar_one_or_none()
        return CheckpointOut.model_validate(cp) if cp else None

    async def delete_by_task(self, task_id: uuid.UUID) -> None:
        cps = (
            (await self._session.execute(select(Checkpoint).where(Checkpoint.task_id == task_id)))
            .scalars()
            .all()
        )
        for cp in cps:
            await self._session.delete(cp)
        if cps:
            await self._session.flush()
