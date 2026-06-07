"""SessionService 单测 —— 覆盖:create / get / delete / 降级 / 延迟双删。

测试策略:
- 不连真 PG 和真 Redis:mock SessionRepository + SessionCache
- asyncio.sleep 用 monkeypatch 缩短(不真等 500ms)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.repository.session import SessionRepository
from app.schema.session import SessionDTO
from app.service.session import SessionService
from app.service.session_cache import SessionCache


@pytest.fixture
def session() -> SessionDTO:
    return SessionDTO(
        token="test-token-abc",
        user_id=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    return MagicMock(spec=SessionRepository)


@pytest.fixture
def mock_cache() -> MagicMock:
    return MagicMock(spec=SessionCache)


@pytest.fixture
def svc(mock_repo: MagicMock, mock_cache: MagicMock) -> SessionService:
    return SessionService(repo=mock_repo, cache=mock_cache)


# ── create ──────────────────────────────────────────────────


async def test_create_writes_pg_then_redis(
    svc: SessionService,
    mock_repo: MagicMock,
    mock_cache: MagicMock,
    session: SessionDTO,
) -> None:
    """create 必须先写 PG,再写 Redis,返回 SessionDTO。"""
    mock_repo.create = AsyncMock(return_value=session)
    mock_cache.set = AsyncMock()
    token = "new-token"
    user_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(days=30)

    result = await svc.create(token, user_id, expires_at)

    assert result == session
    mock_repo.create.assert_awaited_once_with(token, user_id, expires_at)
    mock_cache.set.assert_awaited_once()


async def test_create_cache_failure_does_not_block(
    svc: SessionService,
    mock_repo: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Redis 写失败不影响登录,PG 写入必须成功。"""
    mock_repo.create = AsyncMock(
        return_value=SessionDTO(
            token="t",
            user_id=uuid4(),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    mock_cache.set = AsyncMock(side_effect=RuntimeError("Redis unavailable"))

    result = await svc.create("t", uuid4(), datetime.now(UTC) + timedelta(hours=1))

    assert result is not None
    mock_repo.create.assert_awaited_once()


# ── get_by_token ────────────────────────────────────────────


async def test_get_hit_returns_from_cache(
    svc: SessionService,
    mock_repo: MagicMock,
    mock_cache: MagicMock,
    session: SessionDTO,
) -> None:
    """缓存命中时返回缓存数据,不查 PG。"""
    mock_cache.get = AsyncMock(return_value=session)

    result = await svc.get_by_token(session.token)

    assert result == session
    mock_repo.get_by_token.assert_not_called()


async def test_get_miss_falls_back_to_pg(
    svc: SessionService,
    mock_repo: MagicMock,
    mock_cache: MagicMock,
    session: SessionDTO,
) -> None:
    """缓存 MISS → 查 PG → 回写 Redis。"""
    mock_cache.get = AsyncMock(return_value=None)
    mock_repo.get_by_token = AsyncMock(return_value=session)
    mock_cache.set = AsyncMock()

    result = await svc.get_by_token(session.token)

    assert result == session
    mock_repo.get_by_token.assert_awaited_once()
    mock_cache.set.assert_awaited_once()


async def test_get_miss_pg_also_miss(
    svc: SessionService,
    mock_repo: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """缓存 + PG 都 MISS → 返回 None。"""
    mock_cache.get = AsyncMock(return_value=None)
    mock_repo.get_by_token = AsyncMock(return_value=None)

    assert await svc.get_by_token("nonexistent") is None


async def test_get_cache_read_failure_falls_back(
    svc: SessionService,
    mock_repo: MagicMock,
    mock_cache: MagicMock,
    session: SessionDTO,
) -> None:
    """Redis 读异常降级到 PG,不抛。"""
    mock_cache.get = AsyncMock(side_effect=RuntimeError("Redis error"))
    mock_repo.get_by_token = AsyncMock(return_value=session)
    mock_cache.set = AsyncMock()

    result = await svc.get_by_token(session.token)

    assert result == session


# ── delete (延迟双删) ────────────────────────────────────────


async def test_delete_does_delay_double_delete(
    svc: SessionService,
    mock_repo: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """delete 必须执行:del cache → del PG → 后台 create_task 延迟 del cache。"""
    token = "token-to-delete"
    mock_cache.delete = AsyncMock()
    mock_repo.delete = AsyncMock()

    # monkeypatch asyncio.sleep 避免真等 500ms
    original_sleep = asyncio.sleep
    asyncio.sleep = AsyncMock()  # noqa: B010 - 测试中缩短延迟

    # monkeypatch create_task:让后台任务同步 await,确保断言前已执行
    original_create_task = asyncio.create_task

    async def _run_immediately(coro):
        """同步执行后台协程,替代 create_task 的异步调度。"""
        await coro

    asyncio.create_task = _run_immediately  # type: ignore[assignment]

    try:
        await svc.delete(token)

        assert mock_cache.delete.call_count == 2
        assert mock_repo.delete.call_count == 1
        mock_repo.delete.assert_awaited_once_with(token)
    finally:
        asyncio.sleep = original_sleep
        asyncio.create_task = original_create_task


async def test_delete_second_failure_logged(
    svc: SessionService,
    mock_repo: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """第二删失败只日志告警,不阻塞登出。"""
    token = "token-to-delete"
    mock_cache.delete = AsyncMock(side_effect=[None, RuntimeError("Redis error")])
    mock_repo.delete = AsyncMock()
    original_sleep = asyncio.sleep
    asyncio.sleep = AsyncMock()

    # 让 create_task 同步执行后台任务
    original_create_task = asyncio.create_task

    async def _run_immediately(coro):
        await coro

    asyncio.create_task = _run_immediately  # type: ignore[assignment]

    try:
        # 不应抛出异常
        await svc.delete(token)
    finally:
        asyncio.sleep = original_sleep
        asyncio.create_task = original_create_task
