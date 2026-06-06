"""
ORM 基础类 —— 声明式基类 + 公共 Mixin。

所有 ORM 模型统一使用 UUID 主键 + created_at,便于
- 数据导出/合并不需重生成自增 ID
- 同一行在 dev/test/prod 三环境 ID 一致(seed 场景)
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """声明式基类 —— 所有 ORM 模型继承此类。"""


class UUIDMixin:
    """每条模型都共享的 PK + 创建时间。

    为什么用 UUID 而非自增整数:
    - 后续 Phase 2+ 需要多 agent 协同，UUID 可跨服务无碰撞
    - 数据导出/恢复时不需处理自增 ID 偏移
    """

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_uuid.uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
