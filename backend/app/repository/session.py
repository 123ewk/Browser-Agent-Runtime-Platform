"""SessionRepository —— 以 token 本身为主键,省去额外映射表。

为什么不用自增 id + token 双字段:
- 查 session 永远用 token 查,自增 id 永远用不到,多写一个索引浪费
- 用 token 做主键,delete where token=? 单条 SQL 走主键,比走二级索引快
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model import UserSession
from app.schema.session import SessionDTO


class SessionRepository:
    """查询走主键,无需额外索引,注销直接 DELETE。」"""

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
