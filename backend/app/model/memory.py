"""Memory 模型 —— Phase 1 只建表,为 Phase 2+ 的语义检索做准备。

为什么 Phase 1 只建表:
- 任务的语义检索依赖完整的 agent 执行链路,而 Phase 1 只做 HTTP CRUD
- 先建表保证 migration 一次到位,避免后续加表时需要从零迁移(生产环境可能已经有用户数据)

为什么用 Vector(1024): DeepSeek / MiMo 等 embedding 模型输出是 1024 维向量,固定维度让 pgvector 可以用 IVFFlat 索引加速检索。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.model.user import User


class Memory(Base, UUIDMixin):
    __tablename__ = "memories"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)

    user: Mapped[User] = relationship(back_populates="memories")
