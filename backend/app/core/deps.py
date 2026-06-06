"""FastAPI 依赖注入 —— 提供 AsyncSession + 当前用户。

每个请求创建独立的 AsyncSession,请求结束自动关闭。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.schema.user import UserOut

_bearer = HTTPBearer(auto_error=False)


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """每次请求分配一个 AsyncSession,请求结束关闭。"""
    session: AsyncSession = request.app.state.deps.pg.session()
    try:
        yield session
    finally:
        await session.close()


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    """从 Authorization header 提取 Bearer token,验证后返回当前用户。

    验证链路: token 解码 → 查 Session 表(未过期) → 查 User 表。
    任一失败返 401。
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    user_id = decode_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # 检查 session 是否存在且未过期
    from app.repository.session import SessionRepository

    session_repo = SessionRepository(session)
    sess = await session_repo.get_by_token(credentials.credentials)
    if sess is None or sess.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    from app.repository.user import UserRepository

    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


async def get_current_user_id(
    current_user: UserOut = Depends(get_current_user),
) -> uuid.UUID:
    """便捷依赖:只返回当前用户 ID。"""
    return current_user.id
