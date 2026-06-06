"""认证路由 —— 注册 / 登录 / 注销。

注册: POST /auth/register → 创建用户 + 返回 JWT
登录: POST /auth/login → 验证密码 + 创建 Session + 返回 JWT
注销: POST /auth/logout → 删除 Session
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_session
from app.core.security import create_token, hash_password
from app.repository.session import SessionRepository
from app.repository.user import UserRepository
from app.schema.user import TokenResponse, UserCreate, UserLogin, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
log = structlog.get_logger(__name__)
_bearer = HTTPBearer()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: UserCreate, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    """注册 —— 409 而非 200 避免用户名冲突被当作成功。"""
    user_repo = UserRepository(session)

    existing = await user_repo.get_by_username(body.username)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username taken")

    user = await user_repo.create(body.username, hash_password(body.password))

    token = create_token(user.id)
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    await SessionRepository(session).create(token, user.id, expires_at)

    log.info("auth.register", username=body.username, user_id=str(user.id))
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(body: UserLogin, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    """登录 —— 用 verify_credentials 而非暴露 hashed_password 给路由层,
    防止密码哈希意外泄露到日志或响应体。"""
    user_repo = UserRepository(session)

    user = await user_repo.verify_credentials(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_token(user.id)
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    await SessionRepository(session).create(token, user.id, expires_at)

    log.info("auth.login", username=body.username)
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: UserOut = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> None:
    """注销 —— 主动删 session,不等 token 自然过期。
    降低被窃 token 在有效期内可重放的窗口。"""
    await SessionRepository(session).delete(credentials.credentials)
    log.info("auth.logout", user_id=str(current_user.id))
