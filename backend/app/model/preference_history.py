"""PreferenceHistory 模型 —— user_preferences 的变更审计日志。

作用: user_preferences 的 UNIQUE(user_id, key) 会使更新自动覆盖旧值,
历史丢失不利于审计和回滚。此表记录每次变更的旧值→新值→时间链。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, UUIDMixin


class PreferenceHistory(Base, UUIDMixin):
    __tablename__ = "preference_history"

    preference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_preferences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    old_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_content: Mapped[str] = mapped_column(Text, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
