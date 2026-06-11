"""Task 模型 —— 用字符串存状态而非 Python enum。

为什么状态用 String(20) 而非 Enum:
- 状态值需要写入 JSONB 审计日志 / API 响应,Enum 序列化需要额外 adapter
- 数据库直接查出来就是字符串,不需要做 enum<->str 转换
- 后续加新状态只需改模型文件,不涉及 Enum 类的 import

为什么用 jsonb 存 result: agent 执行结果结构不确定(截图 URL / 错误栈 / 结构化数据),
jsonb 可以容纳任意结构而无需 migration。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
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
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        default=None,
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # V2.5: 可观测增强 — token/成本追踪
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    llm_model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="tasks")
    steps: Mapped[list[TaskStep]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskStep.step_index"
    )
    checkpoints: Mapped[list[Checkpoint]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
