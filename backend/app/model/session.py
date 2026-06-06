"""UserSession 模型 —— 用 token 字符串做主键,无需自增 id。

为什么 token 做主键而非自增 id + token 双字段:
- 查 session 永远用 token 查,自增 id 永远用不到,多一个索引就是多一份写放大
- 注销时 DELETE WHERE token=? 走主键索引,比走二级索引快一个 B+tree 层级
- JWT token 本身已包含随机性和唯一性,无需额外 UUID PK"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base

if TYPE_CHECKING:
    from app.model.user import User


class UserSession(Base):
    __tablename__ = "user_sessions"

    token: Mapped[str] = mapped_column(String(256), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="sessions")
