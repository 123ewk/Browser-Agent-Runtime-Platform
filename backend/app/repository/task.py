"""TaskRepository —— 只实现业务需要的增改查,不提供 delete。

为什么没有 delete:
- 任务的物理删除意味着丢失 agent 执行轨迹,不符合审计要求
- 如果用户想"删除"任务,后续加软删除字段(deleted_at),不走 DELETE SQL
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.model import Task
from app.runtime.protocol.types import TaskState
from app.schema.agent import AgentMetrics
from app.schema.task import TaskCreate, TaskListResponse, TaskOut, TaskUpdate

logger = structlog.get_logger(__name__)

# 白名单: 与 alembic 迁移 4f8a2c1b3d5e 的 CHECK 约束保持同步
# 修改时必须同步: app/runtime/protocol/types.py TaskState + alembic 迁移
_ALLOWED_STATUSES: frozenset[str] = frozenset(s.value for s in TaskState)


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
        self,
        user_id: uuid.UUID,
        dto: TaskCreate,
        task_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
    ) -> TaskOut:
        task = Task(
            id=task_id or uuid.uuid4(),
            user_id=user_id,
            agent_id=agent_id,
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
            # 白名单校验: 拒绝非 enum 值, 防止脏数据写入 DB
            # (DB 层 CHECK 约束是最后防线, 应用层校验先拦一次给清晰错误)
            if dto.status not in _ALLOWED_STATUSES:
                logger.warning(
                    "task.update_status.rejected_invalid_status",
                    task_id=str(id),
                    attempted_status=dto.status,
                )
                raise ValueError(
                    f"非法的 status 值: {dto.status!r}, " f"允许值: {sorted(_ALLOWED_STATUSES)}"
                )
            task.status = dto.status
        if dto.result is not None:
            task.result = dto.result
        await self._session.flush()
        # 显式 refresh: 把 onupdate 触发的列(updated_at)从 DB 拉回 ORM 内存,
        # 避免后续 Pydantic 同步访问 task.updated_at 时触发 lazy load → MissingGreenlet
        await self._session.refresh(task)
        return TaskOut.model_validate(task)

    async def last_task_at_map(self, agent_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
        """每个 agent 的最近任务时间(不限窗口,用于 inactive 判定)

        1 次 GROUP BY 查询,O(#agents) 不随 tasks 总行数增长。
        """
        if not agent_ids:
            return {}
        stmt = (
            select(Task.agent_id, func.max(Task.updated_at).label("last_task_at"))
            .where(Task.agent_id.in_(agent_ids))
            .group_by(Task.agent_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {row.agent_id: row.last_task_at for row in rows}

    async def aggregate_metrics(self, agent_ids: list[uuid.UUID]) -> dict[uuid.UUID, AgentMetrics]:
        """24h + 1h 双窗口聚合(1h 是 24h 的子集,一次全表扫描)

        使用 PostgreSQL COUNT(*) FILTER 语法,一次 GROUP BY 返回所有 agent 的双窗口数据。
        """
        if not agent_ids:
            return {}
        stmt = text(
            """
            SELECT
              agent_id,
              COUNT(*) FILTER (WHERE status = 'completed')
                AS success_count_24h,
              COUNT(*) FILTER (WHERE status IN ('completed', 'failed', 'cancelled'))
                AS terminal_count_24h,
              COUNT(*) FILTER (WHERE status = 'completed'
                AND updated_at >= NOW() - INTERVAL '1 hour')
                AS success_count_1h,
              COUNT(*) FILTER (WHERE status IN ('completed', 'failed', 'cancelled')
                AND updated_at >= NOW() - INTERVAL '1 hour')
                AS terminal_count_1h
            FROM tasks
            WHERE agent_id = ANY(:agent_ids::uuid[])
              AND updated_at >= NOW() - INTERVAL '24 hours'
            GROUP BY agent_id
            """
        )
        result = await self._session.execute(stmt, {"agent_ids": [str(aid) for aid in agent_ids]})
        rows = result.mappings().all()
        return {
            row["agent_id"]: AgentMetrics(
                success_count_24h=row["success_count_24h"],
                terminal_count_24h=row["terminal_count_24h"],
                success_count_1h=row["success_count_1h"],
                terminal_count_1h=row["terminal_count_1h"],
            )
            for row in rows
        }
