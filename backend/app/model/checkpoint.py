"""Checkpoint 模型 —— append 模式存 checkpoint,不使用 upsert。

为什么 append 而非 update-in-place:
- 保留完整的历史 checkpoint 序列,可以回溯 agent 的决策路径
- 崩溃恢复时只需要取最新一条,旧数据在后续加 TTL 清理即可
- update-in-place 需要额外 where 条件甄别"是不是最新的",比 append 多一次查询

为什么单独建表不塞在 Task jsonb 字段: checkpoint 的 state_data 可能非常大(LangGraph 全状态),
单独放在一张表里可以做大字段单独存储,不影响 Task 表的查询性能。"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.model.task import Task


class Checkpoint(Base, UUIDMixin):
    __tablename__ = "checkpoints"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state_data: Mapped[dict] = mapped_column(JSONB, nullable=False)

    task: Mapped[Task] = relationship(back_populates="checkpoints")
