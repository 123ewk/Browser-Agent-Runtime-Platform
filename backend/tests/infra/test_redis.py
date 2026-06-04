"""app.infra.redis 单测 — 覆盖:URL 拼装 / health_check 三路径 / aclose / 工厂 / client 暴露。

测试策略:
- 不连真 Redis:用 MagicMock(spec=Redis) 替换 client,精确控制 ping / aclose
- URL 单测:monkeypatch settings 字段,验 _build_url() 拼装正确性(含/不含密码)
- health_check:成功 / RedisError 失败 / 非 RedisError 异常冒泡 三条路径
- 工厂:patch ConnectionPool.from_url + Redis 构造,验证参数透传 + 客户端类型
- client 属性:必须返回构造期注入的 Redis 实例(供业务层调原生命令)

集成测试(连真 Redis)不在本文件,留待 tests/integration/。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.infra import redis
from app.infra.redis import RedisClient, _build_url, create_redis_client

# ---------- 测试夹具 ----------


def _patch_redis_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    host: str = "redis.local",
    port: int = 6379,
    password: str | None = None,
    db: int = 0,
) -> None:
    """monkeypatch settings 字段,URL 单测隔离全局 state。

    SecretStr.get_secret_value() 用 MagicMock 替代,lambda 默认参数固化避免闭包陷阱。
    password=None 时显式设 settings.redis_password = None,模拟"无密码"本地 dev 场景。
    """
    monkeypatch.setattr(redis.settings, "redis_host", host)
    monkeypatch.setattr(redis.settings, "redis_port", port)
    if password is None:
        monkeypatch.setattr(redis.settings, "redis_password", None)
    else:
        monkeypatch.setattr(
            redis.settings,
            "redis_password",
            MagicMock(get_secret_value=lambda pw=password: pw),
        )
    monkeypatch.setattr(redis.settings, "redis_db", db)


# ---------- URL 拼装 ----------


def test_build_url_without_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """无密码本地开发:URL 必须是 redis://host:port/db,不能含 ":@" 前缀。

    否则部分 Redis 客户端会发空 AUTH 命令,触发 NOAUTH 错误。
    """
    _patch_redis_settings(monkeypatch, host="r.example", port=6380, password=None, db=2)
    assert _build_url() == "redis://r.example:6380/2"


def test_build_url_with_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """有密码生产环境:URL 必须是 redis://:password@host:port/db。

    注意格式:无 user,只有 password,redis-py 解析为"只发 AUTH <password>"。
    """
    _patch_redis_settings(
        monkeypatch,
        host="r.example",
        port=6380,
        password="s3cret",
        db=0,
    )
    assert _build_url() == "redis://:s3cret@r.example:6380/0"


def test_build_url_db_number(monkeypatch: pytest.MonkeyPatch) -> None:
    """redis_db 走路径段(非 query string),redis-py from_url 按段解析。"""
    _patch_redis_settings(monkeypatch, db=15)
    assert _build_url() == "redis://redis.local:6379/15"


# ---------- health_check 三路径 ----------


async def test_health_check_success_returns_true() -> None:
    """PING 成功 → True,ping 被 await 一次。"""
    client = MagicMock(spec=Redis)
    client.ping = AsyncMock(return_value=True)

    assert await RedisClient(client).health_check() is True
    client.ping.assert_awaited_once()


async def test_health_check_redis_error_returns_false() -> None:
    """ConnectionError(连不上 Redis) → False,不抛,业务层据此标记 deps.redis=fail。"""
    client = MagicMock(spec=Redis)
    client.ping = AsyncMock(side_effect=RedisConnectionError("Connection refused"))

    assert await RedisClient(client).health_check() is False
    client.ping.assert_awaited_once()


async def test_health_check_non_redis_error_propagates() -> None:
    """非 RedisError 异常(RuntimeError 等)→ 冒上去,不掩盖代码 bug。

    设计取舍:health_check 只兜底"Redis 相关"异常,其他异常(代码 bug /
    asyncio 异常)仍要冒,便于开发期发现。生产期若 /ready 端点要"始终 200",
    在调用方再包一层 try/except 兜底。
    """
    client = MagicMock(spec=Redis)
    client.ping = AsyncMock(side_effect=RuntimeError("bug"))

    with pytest.raises(RuntimeError, match="bug"):
        await RedisClient(client).health_check()


# ---------- aclose ----------


async def test_aclose_closes_client_and_pool() -> None:
    """aclose 必须 await client.aclose() + connection_pool.aclose()(双层兜底)。"""
    pool = MagicMock(spec=ConnectionPool)
    pool.aclose = AsyncMock()
    client = MagicMock(spec=Redis)
    client.aclose = AsyncMock()
    client.connection_pool = pool

    await RedisClient(client).aclose()
    client.aclose.assert_awaited_once()
    pool.aclose.assert_awaited_once()


# ---------- client 属性暴露 ----------


def test_client_property_returns_underlying_redis() -> None:
    """client 属性必须返回构造期注入的 Redis 实例(供业务层调原生命令)。"""
    raw_client = MagicMock(spec=Redis)
    wrapper = RedisClient(raw_client)
    assert wrapper.client is raw_client


# ---------- 工厂方法 ----------


def test_create_redis_client_uses_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """工厂必须用 settings 拼 URL + 把 max_connections 透传到 ConnectionPool + decode_responses=False。"""
    _patch_redis_settings(monkeypatch, host="h", port=1, password="p", db=3)
    monkeypatch.setattr(redis.settings, "redis_max_connections", 7)

    captured: dict[str, Any] = {}

    class _FakePool:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["ctor_kwargs"] = kwargs
            captured["last_instance"] = self

        @classmethod
        def from_url(cls, url: str, **kwargs: Any) -> _FakePool:
            # 工厂里 ConnectionPool.from_url(url, max_connections=..., decode_responses=...),
            # 这里的 url 走 positional 第一个参,kwargs 走透传,跟原版签名一致
            captured["from_url"] = url
            captured["from_url_kwargs"] = kwargs
            return cls(url=url, **kwargs)

    class _FakeRedis:
        def __init__(self, connection_pool: Any) -> None:
            captured["redis_pool"] = connection_pool

    monkeypatch.setattr(redis, "ConnectionPool", _FakePool)
    monkeypatch.setattr(redis, "Redis", _FakeRedis)

    client = create_redis_client()
    # URL 拼装:密码 ":p" + host:port/db
    assert captured["from_url"] == "redis://:p@h:1/3"
    assert captured["from_url_kwargs"]["max_connections"] == 7
    # decode_responses=False 锁住以防被误改成 True(隐式 decode 引入 bytes/str 混用 bug)
    assert captured["from_url_kwargs"]["decode_responses"] is False
    # Redis 构造时拿到的 pool 必须等于 ConnectionPool.from_url 返回的同一个对象(同一引用)
    assert captured["redis_pool"] is captured["last_instance"]
    assert captured["ctor_kwargs"]["url"] == "redis://:p@h:1/3"
    assert isinstance(client, RedisClient)
