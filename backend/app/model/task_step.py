"""TaskStep 表 —— 任务的每一步执行记录。

记录每一步的动作描述、结构化结果、Token 消耗。
后续 Phase 2+ 与 LangGraph state 同步写入。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.model.task import Task


class TaskStep(Base, UUIDMixin):
    __tablename__ = "task_steps"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)

    task: Mapped[Task] = relationship(back_populates="steps")
