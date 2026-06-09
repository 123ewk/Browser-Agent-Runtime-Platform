"""UserPreference 模型 —— 用户长期偏好/画像,注入 system prompt 定 LLM 基调。

与 Memory 的区别:
- UserPreference: 结构化全量加载 → system prompt (不做向量检索)
- Memory: 向量语义检索 → 会话上下文/知识查询

category 仅用于前端展示,不参与 system prompt 构造逻辑。
key + content 才是核心字段。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.model.user import User


class UserPreference(Base, UUIDMixin):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    key: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    category: Mapped[str] = mapped_column(String(20), nullable=False, default="PREFERENCE")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="EXPLICIT")

    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    user: Mapped[User] = relationship(back_populates="preferences")
