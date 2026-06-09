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
from app.core.deps import get_current_user, get_session, get_session_service
from app.core.security import create_token, hash_password
from app.repository.user import UserRepository
from app.schema.user import TokenResponse, UserCreate, UserLogin, UserOut
from app.service.session import SessionService

router = APIRouter(prefix="/auth", tags=["auth"])
log = structlog.get_logger(__name__)
_bearer = HTTPBearer()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserCreate,
    session: AsyncSession = Depends(get_session),
    svc: SessionService = Depends(get_session_service),
) -> TokenResponse:
    """注册 —— 409 而非 200 避免用户名冲突被当作成功。"""
    user_repo = UserRepository(session)

    existing = await user_repo.get_by_username(body.username)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username taken")

    user = await user_repo.create(body.username, hash_password(body.password))

    token = create_token(user.id)
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    await svc.create(token, user.id, expires_at)

    log.info("auth.register", username=body.username, user_id=str(user.id))
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: UserLogin,
    session: AsyncSession = Depends(get_session),
    svc: SessionService = Depends(get_session_service),
) -> TokenResponse:
    """登录 —— 用 verify_credentials 而非暴露 hashed_password 给路由层,
    防止密码哈希意外泄露到日志或响应体。"""
    user_repo = UserRepository(session)

    user = await user_repo.verify_credentials(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_token(user.id)
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    await svc.create(token, user.id, expires_at)

    log.info("auth.login", username=body.username)
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: UserOut = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    svc: SessionService = Depends(get_session_service),
) -> None:
    """注销 —— 延迟双删,不等 token 自然过期。
    降低被窃 token 在有效期内可重放的窗口。"""
    await svc.delete(credentials.credentials)
    log.info("auth.logout", user_id=str(current_user.id))


@router.get("/me", response_model=UserOut)
async def get_current_user_info(
    current_user: UserOut = Depends(get_current_user),
) -> UserOut:
    """获取当前登录用户信息 —— 前端登录后调用,补全 user.id 和 created_at

    为什么不在 login/register 响应中直接返回 user:
    - TokenResponse 只含 access_token,职责单一
    - 前端拿到 token 后调 /me 获取完整用户信息,解耦认证与用户查询
    """
    return current_user
