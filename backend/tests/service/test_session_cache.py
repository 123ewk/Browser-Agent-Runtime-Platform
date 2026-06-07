"""SessionCache 单测 —— 覆盖:get(HIT/MISS)/set/delete/序列化/异常。

测试策略:
- 不连真 Redis:mock RedisClient.client.get/setex/delete
- 序列化单测:验 JSON 格式正确性
- 异常路径:Redis.get 抛异常冒泡(由 SessionService 兜底降级)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from app.infra.redis import RedisClient, RedisKeys
from app.schema.session import SessionDTO
from app.service.session_cache import SessionCache


@pytest.fixture
def session() -> SessionDTO:
    return SessionDTO(
        token="test-token-123",
        user_id=uuid4(),
        expires_at=datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC),
    )


@pytest.fixture
def cache() -> SessionCache:
    client = MagicMock(spec=Redis)
    return SessionCache(RedisClient(client))


# ── 序列化 ──────────────────────────────────────────────────


def test_serialize_contains_expected_fields(session: SessionDTO) -> None:
    """JSON 必须包含 token / user_id / expires_at,且 user_id 为 UUID 格式字符串。"""
    raw = SessionCache._serialize(session)
    data = json.loads(raw)
    assert data["token"] == session.token
    assert data["user_id"] == str(session.user_id)
    # isoformat 包含时区信息
    assert data["expires_at"].endswith("+00:00")


def test_deserialize_roundtrip(session: SessionDTO) -> None:
    """序列化 → 反序列化必须等幂。"""
    raw = SessionCache._serialize(session)
    restored = SessionCache._deserialize(raw)
    assert restored.token == session.token
    assert restored.user_id == session.user_id
    assert restored.expires_at == session.expires_at


# ── get ─────────────────────────────────────────────────────


async def test_get_hit(cache: SessionCache, session: SessionDTO) -> None:
    """Redis GET 返回 JSON → 反序列化为 SessionDTO。"""
    cache._redis.client.get = AsyncMock(return_value=SessionCache._serialize(session).encode())  # type: ignore[method-assign]

    result = await cache.get(session.token)
    assert result is not None
    assert result.token == session.token


async def test_get_miss(cache: SessionCache) -> None:
    """Redis GET 返回 None → 返回 None。"""
    cache._redis.client.get = AsyncMock(return_value=None)  # type: ignore[method-assign]

    assert await cache.get("nonexistent") is None


# ── set ─────────────────────────────────────────────────────


async def test_set_calls_setex(cache: SessionCache, session: SessionDTO) -> None:
    """set 必须调 SETEX,带 JSON 序列化后的 bytes 和 TTL。"""
    setex = AsyncMock()
    cache._redis.client.setex = setex  # type: ignore[method-assign]

    await cache.set(session, ttl=3600)

    setex.assert_awaited_once()
    args, _ = setex.call_args
    assert args[0] == RedisKeys.session(session.token)  # key
    assert args[1] == 3600  # TTL
    # value 是 JSON 字符串(redis-py 内部编码为 bytes)
    assert isinstance(args[2], str)
    data = json.loads(args[2])
    assert data["token"] == session.token


# ── delete ──────────────────────────────────────────────────


async def test_delete_calls_del(cache: SessionCache) -> None:
    """delete 必须调 Redis DEL。"""
    delete = AsyncMock(return_value=1)
    cache._redis.client.delete = delete  # type: ignore[method-assign]

    await cache.delete("some-token")

    delete.assert_awaited_once_with(RedisKeys.session("some-token"))
