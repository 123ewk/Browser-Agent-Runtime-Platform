"""FastAPI 依赖注入 —— 提供 AsyncSession + 当前用户。

每个请求创建独立的 AsyncSession,请求结束自动关闭。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

# 是 Python typing 模块里的一个特殊常量
# 运行时：值为 False，if TYPE_CHECKING: 里的代码完全不会执行，也不会触发导入
# 类型检查 / IDE 分析时：值为 True，类型检查器（如 mypy、pyright）和 IDE 会执行里面的导入，从而识别类型注解

if TYPE_CHECKING:
    # 解决循环导入问题
    from app.service.session import SessionService

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # 标准 Bearer Token 方案
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.schema.user import UserOut

# 标准的 Bearer Token 认证方案，会自动从请求头的 Authorization: Bearer <token> 字段中提取 Token。
# 默认情况下（auto_error=True），如果请求头中没有 Authorization 字段，或格式不对，FastAPI 会直接抛出 401 错误。
# 当设置为 auto_error=False 时，它不会自动抛出错误，而是在解析失败时返回 None，把控制权交给你自己的代码。
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


async def get_session_service(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SessionService:
    """Depends 工厂:从 request.state 取 RedisClient,组合 SessionService。

    为什么设计为 Depends 而非直接构造:
    - 避免 auth.py 每个路由重复写构造代码
    - 单测可替换 get_session_service 返回 mock,无需起真 Redis
    """
    from app.repository.session import SessionRepository
    from app.service.session import SessionService as _SS
    from app.service.session_cache import SessionCache

    return _SS(
        repo=SessionRepository(session),
        cache=SessionCache(request.app.state.deps.redis),
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
    svc: SessionService = Depends(get_session_service),
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

    sess = await svc.get_by_token(credentials.credentials)
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
