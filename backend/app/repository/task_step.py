"""TaskStepRepository —— 步骤追加写入,不修改历史。

为什么只增不删不改:
- 步骤是审计日志,修改历史会破坏可追溯性
- Phase 2+ 的 LangGraph state 依赖 immutable 步骤序列
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model import TaskStep
from app.schema.task_step import TaskStepOut


class TaskStepRepository:
    """只实现了 create + list_by_task, 没有 update 方法"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        task_id: uuid.UUID,
        step_index: int,
        action: str,
        result: dict | None = None,
        tokens_used: int | None = None,
    ) -> TaskStepOut:
        step = TaskStep(
            task_id=task_id,
            step_index=step_index,
            action=action,
            result=result,
            tokens_used=tokens_used,
        )
        self._session.add(step)
        await self._session.flush()
        return TaskStepOut.model_validate(step)

    async def list_by_task(self, task_id: uuid.UUID) -> list[TaskStepOut]:
        result = await self._session.execute(
            select(TaskStep).where(TaskStep.task_id == task_id).order_by(TaskStep.step_index)
        )
        steps = result.scalars().all()
        return [TaskStepOut.model_validate(s) for s in steps]
