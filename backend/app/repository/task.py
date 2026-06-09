"""TaskRepository —— 只实现业务需要的增改查,不提供 delete。

为什么没有 delete:
- 任务的物理删除意味着丢失 agent 执行轨迹,不符合审计要求
- 如果用户想"删除"任务,后续加软删除字段(deleted_at),不走 DELETE SQL
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model import Task
from app.schema.task import TaskCreate, TaskListResponse, TaskOut, TaskUpdate


class TaskRepository:
    """update 只修改 status 和 result 两个字段,不改 goal。

    为什么 update 设计为只改 status + result:
    - status 由 agent 执行引擎驱动状态机流转
    - result 是执行结束后的产物
    - 其他字段(goal/user_id/created_at)在创建后就不该被修改
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, user_id: uuid.UUID, dto: TaskCreate, task_id: uuid.UUID | None = None
    ) -> TaskOut:
        task = Task(
            id=task_id or uuid.uuid4(),
            user_id=user_id,
            goal=dto.goal,
        )
        self._session.add(task)
        await self._session.flush()
        return TaskOut.model_validate(task)

    async def get_by_id(self, id: uuid.UUID) -> TaskOut | None:
        task = await self._session.get(Task, id)
        return TaskOut.model_validate(task) if task else None

    async def list_by_user(
        self, user_id: uuid.UUID, status: str | None = None, limit: int = 20, offset: int = 0
    ) -> TaskListResponse:
        # 构建查询 + 计数
        base = select(Task).where(Task.user_id == user_id)
        count_q = select(func.count()).select_from(Task).where(Task.user_id == user_id)
        if status:
            base = base.where(Task.status == status)
            count_q = count_q.where(Task.status == status)

        base = base.order_by(Task.created_at.desc()).limit(limit).offset(offset)

        rows = (await self._session.execute(base)).scalars().all()
        total = (await self._session.execute(count_q)).scalar_one()

        return TaskListResponse(
            items=[TaskOut.model_validate(t) for t in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update_status(self, id: uuid.UUID, dto: TaskUpdate) -> TaskOut | None:
        task = await self._session.get(Task, id)
        if task is None:
            return None
        if dto.status is not None:
            task.status = dto.status
        if dto.result is not None:
            task.result = dto.result
        await self._session.flush()
        return TaskOut.model_validate(task)
