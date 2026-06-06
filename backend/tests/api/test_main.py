"""app.main smoke tests — cover /health and /ready endpoints.

Test strategy:
- Use httpx.AsyncClient with app in lifespan context (real startup/shutdown)
- Patch infra factory methods to return mocks (no real PG/Redis/S3/LLM)
- /health: trivial, always 200
- /ready: parallel probe, verify response shape + degraded path
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import app


def _mock_pg(ok: bool = True) -> Any:
    client = MagicMock()
    client.health_check = AsyncMock(return_value=ok)
    client.aclose = AsyncMock()
    return client


def _mock_redis(ok: bool = True) -> Any:
    client = MagicMock()
    client.health_check = AsyncMock(return_value=ok)
    client.aclose = AsyncMock()
    return client


def _mock_s3(ok: bool = True) -> Any:
    client = MagicMock()
    client.health_check = AsyncMock(return_value=ok)
    client.aclose = AsyncMock()
    return client


def _mock_llm(content: str = "pong", raise_exc: bool = False) -> Any:
    client = MagicMock()
    if raise_exc:
        client.chat = AsyncMock(side_effect=RuntimeError("llm down"))
    else:
        resp = MagicMock()
        resp.content = content
        client.chat = AsyncMock(return_value=resp)
    client.aclose = AsyncMock()
    return client


# ---------- /health ----------


async def test_health_returns_ok() -> None:
    """Liveness probe always returns 200 with status=ok."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------- /ready — all deps healthy ----------


async def test_ready_all_ok() -> None:
    """When all 4 deps are healthy, /ready returns status=ok."""
    with (
        patch("app.main.create_postgres_client", return_value=_mock_pg()),
        patch("app.main.create_redis_client", return_value=_mock_redis()),
        patch("app.main.create_s3_client", return_value=_mock_s3()),
        patch("app.main.create_mimo_provider", return_value=_mock_llm()),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ready")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["deps"]["postgres"] == "ok"
    assert body["deps"]["redis"] == "ok"
    assert body["deps"]["s3"] == "ok"
    assert body["deps"]["llm"] == "ok"


# ---------- /ready — one dep down ----------


async def test_ready_degraded_when_pg_down() -> None:
    """When postgres health_check returns False, status=degraded."""
    with (
        patch("app.main.create_postgres_client", return_value=_mock_pg(ok=False)),
        patch("app.main.create_redis_client", return_value=_mock_redis()),
        patch("app.main.create_s3_client", return_value=_mock_s3()),
        patch("app.main.create_mimo_provider", return_value=_mock_llm()),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ready")

    body = resp.json()
    assert body["status"] == "degraded"
    assert body["deps"]["postgres"] == "fail"
    assert body["deps"]["redis"] == "ok"


# ---------- /ready — LLM probe fails ----------


async def test_ready_degraded_when_llm_fails() -> None:
    """When LLM chat raises, llm=degraded, other deps still ok."""
    with (
        patch("app.main.create_postgres_client", return_value=_mock_pg()),
        patch("app.main.create_redis_client", return_value=_mock_redis()),
        patch("app.main.create_s3_client", return_value=_mock_s3()),
        patch("app.main.create_mimo_provider", return_value=_mock_llm(raise_exc=True)),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ready")

    body = resp.json()
    assert body["status"] == "degraded"
    assert body["deps"]["llm"] == "fail"
    assert body["deps"]["postgres"] == "ok"
