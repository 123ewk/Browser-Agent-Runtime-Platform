"""CheckpointRepository —— 每次创建都增行 append,不覆盖。

为什么 append 而非 upsert:
- 保留历史 checkpoint 可回溯 agent 决策路径
- 崩溃恢复时只取最新的,旧数据自动被 time-decay 清理(后续加 TTL)

新增 get_previous_by_task: 当最新 checkpoint 损坏时,回退到上一版本。
"""

from __future__ import annotations

import json
import uuid
from hashlib import sha256

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model import Checkpoint
from app.schema.checkpoint import CheckpointOut


class CheckpointRepository:
    """get_latest_by_task 取最新一条,delete_by_task 在任务完成时清理"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        task_id: uuid.UUID,
        state_data: dict,
        *,
        checkpoint_type: str = "auto",
        schema_version: int = 1,
        snapshot_hash: str | None = None,
    ) -> CheckpointOut:
        """创建 checkpoint。

        snapshot_hash 由调用方(CheckpointManager._compute_hash)传入,
        确保存储和校验使用同一 hash 算法。为兼容旧调用方保留自动计算逻辑。
        """
        if snapshot_hash is None:
            raw = json.dumps(state_data, sort_keys=True).encode("utf-8")
            snapshot_hash = sha256(raw).hexdigest()
        cp = Checkpoint(
            task_id=task_id,
            state_data=state_data,
            checkpoint_type=checkpoint_type,
            schema_version=schema_version,
            snapshot_hash=snapshot_hash,
        )
        self._session.add(cp)
        await self._session.flush()
        return CheckpointOut.model_validate(cp)

    async def get_latest_by_task(self, task_id: uuid.UUID) -> CheckpointOut | None:
        """取 task 最新一条 checkpoint(按 created_at desc)"""
        result = await self._session.execute(
            select(Checkpoint)
            .where(Checkpoint.task_id == task_id)
            .order_by(desc(Checkpoint.created_at))
            .limit(1)
        )
        cp = result.scalar_one_or_none()
        return CheckpointOut.model_validate(cp) if cp else None

    async def get_previous_by_task(
        self, task_id: uuid.UUID, before_id: uuid.UUID
    ) -> CheckpointOut | None:
        """取 task 在指定 checkpoint 之前的最近一条(损坏回退用)"""
        result = await self._session.execute(
            select(Checkpoint)
            .where(Checkpoint.task_id == task_id)
            .where(Checkpoint.id != before_id)
            .order_by(desc(Checkpoint.created_at))
            .limit(1)
        )
        cp = result.scalar_one_or_none()
        return CheckpointOut.model_validate(cp) if cp else None

    async def list_by_task(
        self, task_id: uuid.UUID, limit: int = 20, offset: int = 0
    ) -> list[CheckpointOut]:
        """列出 task 所有 checkpoint(分页),用于运维/调试"""
        result = await self._session.execute(
            select(Checkpoint)
            .where(Checkpoint.task_id == task_id)
            .order_by(desc(Checkpoint.created_at))
            .offset(offset)
            .limit(limit)
        )
        return [CheckpointOut.model_validate(cp) for cp in result.scalars().all()]

    async def delete_by_task(self, task_id: uuid.UUID) -> None:
        """删除 task 所有 checkpoint(任务完成时清理)"""
        cps = (
            (await self._session.execute(select(Checkpoint).where(Checkpoint.task_id == task_id)))
            .scalars()
            .all()
        )
        for cp in cps:
            await self._session.delete(cp)
        if cps:
            await self._session.flush()
