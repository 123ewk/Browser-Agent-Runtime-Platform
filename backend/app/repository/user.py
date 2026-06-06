"""UserRepository —— 用户 CRUD + 凭据验证。

密码哈希由 verify_credentials 内部处理,调用方只需传明文密码。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.model import User
from app.schema.user import UserOut


class UserRepository:
    """返回 UserOut 不含 hashed_password,防止调用方意外序列化泄露。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, username: str, hashed_password: str) -> UserOut:
        user = User(
            username=username,
            hashed_password=hashed_password,
            id=uuid.uuid4(),
            created_at=datetime.now(UTC),
        )
        self._session.add(user)
        await self._session.flush()
        return UserOut.model_validate(user)

    async def get_by_username(self, username: str) -> UserOut | None:
        result = await self._session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        return UserOut.model_validate(user) if user else None

    async def get_by_id(self, id: uuid.UUID) -> UserOut | None:
        user = await self._session.get(User, id)
        return UserOut.model_validate(user) if user else None

    async def verify_credentials(self, username: str, password: str) -> UserOut | None:
        """验证用户名密码,成功返回 UserOut,失败返回 None。

        直接在仓库方法内验证,避免调用方接触 hashed_password。
        """
        result = await self._session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user is None or not verify_password(password, user.hashed_password):
            return None
        return UserOut.model_validate(user)
