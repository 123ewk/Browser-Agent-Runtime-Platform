"""Task 表 —— 用户任务主记录。

包含任务目标、当前状态、最终结构结果(jsonb)。
状态机: PENDING → RUNNING → WAITING_USER ⇄ RUNNING → COMPLETED / FAILED / CANCELLED
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.model.checkpoint import Checkpoint
    from app.model.task_step import TaskStep
    from app.model.user import User


class Task(Base, UUIDMixin):
    __tablename__ = "tasks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="tasks")
    steps: Mapped[list[TaskStep]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskStep.step_index"
    )
    checkpoints: Mapped[list[Checkpoint]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
