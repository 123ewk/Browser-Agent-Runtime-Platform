"""User 表 —— 存储用户注册信息和密码哈希。

密码用 bcrypt 哈希,不在数据库存储明文。
SecretStr 在日志/异常时自动脱敏,即使意外序列化也不会泄露。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.model.memory import Memory
    from app.model.session import UserSession
    from app.model.task import Task


class User(Base, UUIDMixin):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)

    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    tasks: Mapped[list[Task]] = relationship(back_populates="user", cascade="all, delete-orphan")
    memories: Mapped[list[Memory]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
