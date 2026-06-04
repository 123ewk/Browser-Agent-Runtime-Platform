"""app.infra.postgres 单测 — 覆盖:DSN 拼装 / health_check 三路径 / aclose / 工厂。

测试策略:
- 不连真 PG:用 MagicMock(spec=AsyncEngine) 替换 engine,精确控制 connect/dispose
- DSN 单测:monkeypatch settings 字段,验 _build_dsn() 拼装正确性
- health_check:成功 / SQLAlchemyError 失败 / 非 SQLAlchemy 异常冒泡 三条路径
- 工厂:patch create_async_engine,验证参数透传 + 客户端类型

集成测试(连真 PG)不在本文件,留待 tests/integration/。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.infra import postgres
from app.infra.postgres import PostgresClient, _build_dsn, create_postgres_client

# ---------- 测试夹具 ----------


def _patch_pg_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    host: str = "db.local",
    port: int = 5432,
    user: str = "agent",
    password: str = "secret",
    db: str = "agent_runtime",
) -> None:
    """monkeypatch settings 字段,DSN 单测隔离全局 state。

    SecretStr.get_secret_value() 用 MagicMock 替代,lambda 默认参数固化避免闭包陷阱。
    """
    monkeypatch.setattr(postgres.settings, "postgres_host", host)
    monkeypatch.setattr(postgres.settings, "postgres_port", port)
    monkeypatch.setattr(postgres.settings, "postgres_user", user)
    monkeypatch.setattr(
        postgres.settings,
        "postgres_password",
        MagicMock(get_secret_value=lambda pw=password: pw),
    )
    monkeypatch.setattr(postgres.settings, "postgres_db", db)


def _ok_conn_ctx() -> Any:
    """成功路径:async with engine.connect() → conn.execute(SELECT 1) → OK。"""
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=MagicMock())
    return _acm_yield(conn)


def _fail_conn_ctx(exc: BaseException) -> Any:
    """失败路径:enter 时 raise,模拟连不上 PG / 协议错误。"""
    return _acm_raise(exc)


def _acm_yield(value: Any) -> Any:
    """通用 async context manager 工厂:正常 yield value。"""

    @asynccontextmanager
    async def _ctx() -> AsyncIterator[Any]:
        yield value

    return _ctx()


def _acm_raise(exc: BaseException) -> Any:
    """通用 async context manager 工厂:enter 时 raise exc。"""

    @asynccontextmanager
    async def _ctx() -> AsyncIterator[Any]:
        raise exc
        yield  # noqa: ERA001 — 仅满足 asynccontextmanager 签名

    return _ctx()


# ---------- DSN 拼装 ----------


def test_build_dsn_uses_asyncpg_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    """DSN 必须走 postgresql+asyncpg 协议(SQLAlchemy 2.x async 唯一正确协议)。"""
    _patch_pg_settings(
        monkeypatch,
        host="db.example.com",
        port=5433,
        user="alice",
        password="s3cret",
        db="mydb",
    )
    assert _build_dsn() == "postgresql+asyncpg://alice:s3cret@db.example.com:5433/mydb"


def test_build_dsn_passes_through_special_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    """密码含特殊字符时仍能正确拼装(urlencode 由 asyncpg 驱动处理)。

    生产环境应避免密码含 @ / :,但 SecretStr 本身不强制,本测试只验拼装层不破坏。
    """
    _patch_pg_settings(monkeypatch, password="p@ss:w/rd")
    dsn = _build_dsn()
    assert "p@ss:w/rd" in dsn


# ---------- health_check 三路径 ----------


async def test_health_check_success_returns_true() -> None:
    """SELECT 1 成功 → True,conn.execute 被 await 一次。"""
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=MagicMock())
    engine = MagicMock(spec=AsyncEngine)
    engine.connect = MagicMock(return_value=_acm_yield(conn))

    client = PostgresClient(engine)
    assert await client.health_check() is True
    conn.execute.assert_awaited_once()


async def test_health_check_sqlalchemy_error_returns_false() -> None:
    """OperationalError(连不上 PG)→ False,不抛,业务层据此标记 deps.postgres=fail。

    SQLAlchemy 2.x OperationalError 第三个 orig 参数类型是 BaseException(非 None),
    用一个真实 OSError 包裹模拟底层连接错误。
    """
    engine = MagicMock(spec=AsyncEngine)
    engine.connect = MagicMock(
        return_value=_acm_raise(OperationalError("conn refused", None, OSError("refused")))
    )
    assert await PostgresClient(engine).health_check() is False


async def test_health_check_non_sqlalchemy_error_propagates() -> None:
    """非 SQLAlchemy 异常(RuntimeError 等)→ 冒上去,不掩盖代码 bug。

    设计取舍:health_check 只兜底"数据库相关"异常,其他异常(代码 bug /
    asyncio 异常)仍要冒,便于开发期发现。生产期若 /ready 端点要"始终 200",
    在调用方再包一层 try/except 兜底。
    """
    engine = MagicMock(spec=AsyncEngine)
    engine.connect = MagicMock(return_value=_acm_raise(RuntimeError("bug")))
    with pytest.raises(RuntimeError, match="bug"):
        await PostgresClient(engine).health_check()


# ---------- aclose ----------


async def test_aclose_calls_engine_dispose() -> None:
    """aclose 必须 await engine.dispose()(释放连接池,FastAPI shutdown 用)。"""
    engine = MagicMock(spec=AsyncEngine)
    engine.dispose = AsyncMock()
    await PostgresClient(engine).aclose()
    engine.dispose.assert_awaited_once()


# ---------- 工厂方法 ----------


def test_create_postgres_client_uses_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """工厂必须用 settings 字段拼 DSN + 把 pool_size/max_overflow/pool_pre_ping 透传。"""
    _patch_pg_settings(monkeypatch, host="h", port=1, user="u", password="p", db="d")
    monkeypatch.setattr(postgres.settings, "postgres_pool_size", 5)
    monkeypatch.setattr(postgres.settings, "postgres_max_overflow", 7)

    captured: dict[str, Any] = {}

    def _fake_create(url: str, **kwargs: Any) -> Any:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return MagicMock(spec=AsyncEngine)

    monkeypatch.setattr(postgres, "create_async_engine", _fake_create)

    client = create_postgres_client()
    assert captured["url"] == "postgresql+asyncpg://u:p@h:1/d"
    assert captured["kwargs"]["pool_size"] == 5
    assert captured["kwargs"]["max_overflow"] == 7
    # pool_pre_ping=True 显式写出来便于排错,这里锁住以防默认值被改
    assert captured["kwargs"]["pool_pre_ping"] is True
    assert isinstance(client, PostgresClient)
