"""Agent ORM 模型 —— 浏览器自动化 Agent 的数据库表示。

V2 引入,替代 V1 硬编码单 agent。支持多类型 agent(browser/data_analysis/vision),
当前仅有 browser 类型。is_default 通过部分唯一索引保证只有一行 TRUE。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, UUIDMixin


class Agent(Base, UUIDMixin):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="browser")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
