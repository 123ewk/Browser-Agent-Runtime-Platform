"""Checkpoint 表 —— Agent 状态持久化。

存储序列化的 LangGraph StateGraph 状态,用于崩溃恢复和任务 resume。
每次 create checkpoint 时增行 append,get_latest 取最新一条。
"""

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
