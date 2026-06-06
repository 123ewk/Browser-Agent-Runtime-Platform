"""SessionRepository —— 服务端会话管理。

JWT token 作为主键,支持按需注销。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model import UserSession
from app.schema.session import SessionDTO


class SessionRepository:
    """会话数据访问 —— token 为主键,增删查。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, token: str, user_id: uuid.UUID, expires_at: datetime) -> SessionDTO:
        sess = UserSession(token=token, user_id=user_id, expires_at=expires_at)
        self._session.add(sess)
        await self._session.flush()
        return SessionDTO(token=sess.token, user_id=sess.user_id, expires_at=sess.expires_at)

    async def get_by_token(self, token: str) -> SessionDTO | None:
        result = await self._session.execute(select(UserSession).where(UserSession.token == token))
        sess = result.scalar_one_or_none()
        if sess is None:
            return None
        return SessionDTO(token=sess.token, user_id=sess.user_id, expires_at=sess.expires_at)

    async def delete(self, token: str) -> None:
        sess = await self._session.get(UserSession, token)
        if sess:
            await self._session.delete(sess)
            await self._session.flush()
