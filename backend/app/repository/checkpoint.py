"""CheckpointRepository —— 每次创建都增行 append,不覆盖。

为什么 append 而非 upsert:
- 保留历史 checkpoint 可回溯 agent 决策路径
- 崩溃恢复时只取最新的,旧数据自动被 time-decay 清理(后续加 TTL)
"""

from __future__ import annotations

import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model import Checkpoint
from app.schema.checkpoint import CheckpointOut


class CheckpointRepository:
    """get_latest_by_task 取最新一条,delete_by_task 在任务完成时清理"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task_id: uuid.UUID, state_data: dict) -> CheckpointOut:
        cp = Checkpoint(task_id=task_id, state_data=state_data)
        self._session.add(cp)
        await self._session.flush()  # flush()：预提交刷新，把内存里新增 / 修改的数据，立刻生成 SQL 发给数据库、写入临时缓存，但不真正落地到磁盘、不提交事务
        # Pydantic 官方校验方法把变量cp塞进CheckpointOut模板,自动校验字段类型、必填项合不合法，合法就转成 CheckpointOut 结构化对象，非法直接抛校验异常
        return CheckpointOut.model_validate(cp)

    async def get_latest_by_task(self, task_id: uuid.UUID) -> CheckpointOut | None:
        result = await self._session.execute(
            select(Checkpoint)
            .where(Checkpoint.task_id == task_id)
            .order_by(desc(Checkpoint.created_at))
            .limit(1)
        )
        cp = (
            result.scalar_one_or_none()
        )  # scalar_one_or_none()：返回结果集的第一个元素,如果为空则返回 None
        return CheckpointOut.model_validate(cp) if cp else None

    async def delete_by_task(self, task_id: uuid.UUID) -> None:
        cps = (
            (await self._session.execute(select(Checkpoint).where(Checkpoint.task_id == task_id)))
            .scalars()
            .all()
        )  # .scalars()：只取出 ORM 实体对象，剔除元组包装,从数据库查出来的单行数据，包装成 Python 对象，就是 ORM 实体对象
        for cp in cps:
            await self._session.delete(
                cp
            )  # 只是在会话内存标记这条数据要删除，不会立刻执行 DELETE SQL、不删库,自动同步缓存，适合少量数据
            # execute(delete(表).where()),立刻执行 DELETE 语句，批量删、少查库，不同步缓存，适合批量删除
        if cps:
            await self._session.flush()
