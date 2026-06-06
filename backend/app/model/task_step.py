"""TaskStep 模型 —— 不可变审计日志,不是普通业务表。

为什么 immutable(只增不改):
- 步骤是 agent 执行轨迹的审计依据,修改历史等同于伪造记录
- LangGraph 的 state replay 依赖精确的 step 序列,乱改会导致状态恢复错乱
- 业务上不存在"编辑历史步骤"的需求

为什么不在 Task 表的 jsonb 字段里存步骤列表: 步骤量可能很大(一个任务上百步),
独立表可以分页查询并按 step_index 做断点续传。"""

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
