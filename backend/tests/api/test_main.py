"""app.main 冒烟测试 —— 覆盖 /health 和 /ready 端点。

测试策略:
- 使用 httpx.AsyncClient + ASGITransport
- httpx.ASGITransport 不触发 FastAPI lifespan, 通过 app.state 手动注入 mock deps
- /health: 简单探针, 永远返回 200
- /ready: 并行探测, 验证响应格式 + 降级路径
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

from app.core.state import InfraDeps
from app.main import app


def _mock_pg(ok: bool = True) -> Any:
    """构造 Mock PostgresClient。"""
    from app.infra.postgres import PostgresClient

    client = MagicMock(spec=PostgresClient)
    client.health_check = AsyncMock(return_value=ok)
    client.aclose = AsyncMock()
    return client


def _mock_redis(ok: bool = True) -> Any:
    """构造 Mock RedisClient。"""
    from app.infra.redis import RedisClient

    client = MagicMock(spec=RedisClient)
    client.health_check = AsyncMock(return_value=ok)
    client.aclose = AsyncMock()
    return client


def _mock_s3(ok: bool = True) -> Any:
    """构造 Mock S3Client。"""
    from app.infra.s3 import S3Client

    client = MagicMock(spec=S3Client)
    client.health_check = AsyncMock(return_value=ok)
    client.aclose = AsyncMock()
    return client


def _mock_llm(content: str = "pong", raise_exc: bool = False) -> Any:
    """构造 Mock ChatLLM Provider。"""
    from app.infra.llm import ChatLLM

    client = MagicMock(spec=ChatLLM)
    if raise_exc:
        client.chat = AsyncMock(side_effect=RuntimeError("llm down"))
    else:
        resp = MagicMock()
        resp.content = content
        client.chat = AsyncMock(return_value=resp)
    client.aclose = AsyncMock()
    return client


def _make_deps(
    pg_ok: bool = True,
    redis_ok: bool = True,
    s3_ok: bool = True,
    llm_content: str = "pong",
    llm_raise: bool = False,
) -> InfraDeps:
    """构造 Mock InfraDeps, 直接注入 app.state (httpx 不触发 lifespan)。"""
    return InfraDeps(
        pg=_mock_pg(pg_ok),
        redis=_mock_redis(redis_ok),
        s3=_mock_s3(s3_ok),
        llm=_mock_llm(content=llm_content, raise_exc=llm_raise),
    )


# ---------- /health ----------


async def test_health_returns_ok() -> None:
    """存活探针永远返回 200, status=ok。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------- /ready —— 所有依赖健康 ----------


async def test_ready_all_ok() -> None:
    """所有 4 个依赖健康时, /ready 返回 status=ok。"""
    app.state.deps = _make_deps()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ready")
    finally:
        del app.state.deps

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["deps"]["postgres"] == "ok"
    assert body["deps"]["redis"] == "ok"
    assert body["deps"]["s3"] == "ok"
    assert body["deps"]["llm"] == "ok"


# ---------- /ready —— 单个依赖宕机 ----------


async def test_ready_degraded_when_pg_down() -> None:
    """postgres health_check 返回 False 时, status=degraded。"""
    app.state.deps = _make_deps(pg_ok=False)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ready")
    finally:
        del app.state.deps

    body = resp.json()
    assert body["status"] == "degraded"
    assert body["deps"]["postgres"] == "fail"
    assert body["deps"]["redis"] == "ok"


# ---------- /ready —— LLM 探测失败 ----------


async def test_ready_degraded_when_llm_fails() -> None:
    """LLM chat 抛出异常时, llm=degraded, 其他依赖仍 ok。"""
    app.state.deps = _make_deps(llm_raise=True)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ready")
    finally:
        del app.state.deps

    body = resp.json()
    assert body["status"] == "degraded"
    assert body["deps"]["llm"] == "fail"
    assert body["deps"]["postgres"] == "ok"
