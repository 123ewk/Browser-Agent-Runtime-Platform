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
    """每次请求分配独立 AsyncSession,请求结束自动关闭。

    为什么用 yield 而非 context manager: FastAPI Depends 的
    generator 模式在响应返回后执行 finally,保证连接不泄漏。
    """
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
    """验证 Bearer token → 返回当前用户,失败返 401。

    为什么先查 Session 再查 User: 两步独立验证可以区分
    "token 已过期/被注销"和"用户已被删除"两个场景,
    运维排查时日志更精确。
    为什么用 Depends 而非中间件: 中间件拦截所有路由,
    连 /health 也要过一道认证;Depends 只作用于需要的路由。
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
