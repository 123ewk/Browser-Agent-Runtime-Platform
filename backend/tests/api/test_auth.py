"""Auth API 冒烟测试 —— 注册/登录/注销。

测试策略(延续 test_main.py 风格):
- httpx.ASGITransport 不触发 lifespan,直接注 mock deps
- 用 mock AsyncSession 模拟数据库交互
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

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

    client = MagicMock(spec=RedisClient)
    client.health_check = AsyncMock(return_value=True)
    client.aclose = AsyncMock()
    return client


def _mock_s3() -> Any:
    from app.infra.s3 import S3Client

    client = MagicMock(spec=S3Client)
    client.health_check = AsyncMock(return_value=True)
    client.aclose = AsyncMock()
    return client


def _mock_llm() -> Any:
    from app.infra.llm import ChatLLM

    client = MagicMock(spec=ChatLLM)
    client.aclose = AsyncMock()
    return client


def _new_mock_session() -> tuple[MagicMock, MagicMock]:
    """构造 mock session + 返回的 mock pg client。"""
    ses = MagicMock()
    ses.add = MagicMock()
    ses.flush = AsyncMock()
    ses.commit = AsyncMock()
    ses.rollback = AsyncMock()
    ses.execute = AsyncMock()
    ses.get = AsyncMock()
    ses.close = AsyncMock()
    pg = _mock_pg(ses)
    return ses, pg


def _inject_deps(session: MagicMock, pg: MagicMock) -> None:
    from app.core.state import InfraDeps

    app.state.deps = InfraDeps(
        pg=pg,
        redis=_mock_redis(),
        s3=_mock_s3(),
        llm=_mock_llm(),
    )


def _make_hashed(password: str) -> str:
    from bcrypt import gensalt, hashpw

    return hashpw(password.encode(), gensalt()).decode()


async def test_register_success() -> None:
    """注册新用户应返回 201 + JWT。"""
    ses, pg = _new_mock_session()
    _inject_deps(ses, pg)

    # get_by_username → 用户不存在,create → add + flush
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    ses.execute = AsyncMock(return_value=mock_result)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auth/register", json={"username": "eve", "password": "pass1234"})
    assert resp.status_code == 201
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


async def test_register_duplicate() -> None:
    """重复注册应返回 409。"""
    ses, pg = _new_mock_session()
    _inject_deps(ses, pg)

    from app.model import User

    existing = User(
        id=_uuid.uuid4(),
        username="eve",
        hashed_password="xxx",
        created_at=datetime.now(UTC),
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=existing)
    ses.execute = AsyncMock(return_value=mock_result)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auth/register", json={"username": "eve", "password": "pass1234"})
    assert resp.status_code == 409


async def test_login_success() -> None:
    """正确的用户名/密码应返回 200 + JWT。"""
    ses, pg = _new_mock_session()
    _inject_deps(ses, pg)

    hashed = _make_hashed("pass1234")
    mock_user = MagicMock()
    mock_user.username = "frank"
    mock_user.hashed_password = hashed
    mock_user.id = _uuid.uuid4()
    mock_user.created_at = datetime.now(UTC)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_user)
    ses.execute = AsyncMock(return_value=mock_result)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auth/login", json={"username": "frank", "password": "pass1234"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password() -> None:
    """错误密码应返回 401。"""
    ses, pg = _new_mock_session()
    _inject_deps(ses, pg)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    ses.execute = AsyncMock(return_value=mock_result)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auth/login", json={"username": "frank", "password": "wrong"})
    assert resp.status_code == 401


async def test_register_empty_username() -> None:
    """空用户名应返回 422(validation error)。"""
    ses, pg = _new_mock_session()
    _inject_deps(ses, pg)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auth/register", json={"username": "", "password": "pass1234"})
    assert resp.status_code == 422


async def test_register_short_password() -> None:
    """过短密码应返回 422。"""
    ses, pg = _new_mock_session()
    _inject_deps(ses, pg)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auth/register", json={"username": "grace", "password": "12"})
    assert resp.status_code == 422
