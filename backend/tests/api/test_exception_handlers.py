"""异常分类器测试 —— 验证 4 类异常映射到正确的状态码与响应体。

测试策略:
- 复用 test_auth.py 的 mock deps 装配套路
- 通过 mock ses.execute 抛不同异常,触发路由路径上的失败
- 验证响应 status_code + body.error_type
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DBAPIError, OperationalError

from app.main import app


def _mock_pg(mock_session: MagicMock) -> Any:
    from app.infra.postgres import PostgresClient

    pg = MagicMock(spec=PostgresClient)
    pg.session = MagicMock(return_value=mock_session)
    pg.health_check = AsyncMock(return_value=True)
    pg.aclose = AsyncMock()
    return pg


def _mock_redis() -> Any:
    from app.infra.redis import RedisClient

    c = MagicMock(spec=RedisClient)
    c.health_check = AsyncMock(return_value=True)
    c.aclose = AsyncMock()
    return c


def _mock_s3() -> Any:
    from app.infra.s3 import S3Client

    c = MagicMock(spec=S3Client)
    c.health_check = AsyncMock(return_value=True)
    c.aclose = AsyncMock()
    return c


def _mock_llm() -> Any:
    from app.infra.llm import ChatLLM

    c = MagicMock(spec=ChatLLM)
    c.aclose = AsyncMock()
    return c


def _inject_deps(session: MagicMock) -> None:
    from app.core.state import InfraDeps

    # get_session 的 finally 块调用 commit/rollback/close,必须用 AsyncMock
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    app.state.deps = InfraDeps(
        pg=_mock_pg(session),
        redis=_mock_redis(),
        s3=_mock_s3(),
        llm=_mock_llm(),
    )


# ---------- 1. 基础设施错误 → 503 ----------


async def test_operational_error_returns_503() -> None:
    """DB 连不上(OperationalError)→ 503 + error_type=database_unavailable。"""
    ses = MagicMock()
    ses.execute = AsyncMock(
        side_effect=OperationalError("statement", {}, Exception("connection refused"))
    )
    _inject_deps(ses)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/auth/register", json={"username": "alice", "password": "pass1234"}
        )

    assert resp.status_code == 503
    body = resp.json()
    assert body["error_type"] == "database_unavailable"
    assert "retry" in body["detail"].lower()


async def test_dbapi_error_returns_503() -> None:
    """DB 协议/认证错(DBAPIError,含 asyncpg InvalidPasswordError)→ 503 + database_error。"""
    ses = MagicMock()
    ses.execute = AsyncMock(side_effect=DBAPIError("statement", {}, Exception("auth failed")))
    _inject_deps(ses)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auth/register", json={"username": "bob", "password": "pass1234"})

    assert resp.status_code == 503
    body = resp.json()
    assert body["error_type"] == "database_error"


# ---------- 2. 业务错误透传(不变成 503)----------


async def test_http_exception_passes_through_as_409() -> None:
    """业务层 HTTPException(用户名冲突)→ 仍是 409,error_type 字段不应出现。

    验证 §2 边界:我们的 handler 不能截胡 HTTPException,否则业务状态码全乱。
    """
    import uuid as _uuid
    from datetime import UTC, datetime

    from app.model import User

    ses = MagicMock()
    existing = User(
        id=_uuid.uuid4(),
        username="carol",
        hashed_password="x",
        created_at=datetime.now(UTC),
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=existing)
    ses.execute = AsyncMock(return_value=mock_result)
    _inject_deps(ses)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/auth/register", json={"username": "carol", "password": "pass1234"}
        )

    assert resp.status_code == 409
    assert "error_type" not in resp.json()  # 业务错误用 FastAPI 默认 detail 字段


# ---------- 3. 请求体校验透传(不变成 503)----------


async def test_validation_error_passes_through_as_422() -> None:
    """Pydantic 校验失败 → 仍是 422,不归类为 infra 错误。"""
    ses = MagicMock()
    _inject_deps(ses)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auth/register", json={"username": "", "password": "x"})

    assert resp.status_code == 422
