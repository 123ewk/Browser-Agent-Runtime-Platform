"""User 模型 —— hashed_password 只在入库前和验证时使用,不出序列化层。

为什么用 bcrypt 而非 SHA256: 密码需要抗彩虹表,计算慢反而安全;
SHA256 是快速哈希,适合校验文件完整性,不适合密码存储。

为什么 hashed_password 不被包含在 UserOut Pydantic schema 中:
防止调用方(API handler)意外将 password hash 序列化进响应体。
密码 hash 只在 UserRepository.verify_credentials 内部使用。"""

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
