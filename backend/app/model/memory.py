"""Memory 表 —— 用户跨会话记忆存储。

使用 pgvector 存储 embedding 向量,支持语义相似度检索。
Phase 1 只建表 + pgvector 扩展,写入/查询逻辑 Phase 2+ 实现。
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
