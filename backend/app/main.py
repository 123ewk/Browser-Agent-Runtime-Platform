"""FastAPI application entry point.

Responsibilities:
- Manage infra client lifecycle via lifespan (create on startup, release on shutdown)
- Provide /health (liveness) and /ready (readiness with parallel deps probe) endpoints
- Mount API router for Phase 1+ business routes

Why lifespan instead of deprecated @app.on_event:
- FastAPI 0.103+ recommends lifespan context manager
- Naturally pairs startup/shutdown, preventing resource leaks
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import configure_logging
from app.infra.llm import MiMo, create_mimo_provider
from app.infra.postgres import PostgresClient, create_postgres_client
from app.infra.redis import RedisClient, create_redis_client
from app.infra.s3 import S3Client, create_s3_client

log = structlog.get_logger(__name__)


# --- Response Models ---


class HealthResponse(BaseModel):
    """Liveness probe response - FastAPI is alive."""

    status: str = "ok"


class ReadyResponse(BaseModel):
    """Readiness probe response - each dep checked in parallel."""

    status: str
    deps: dict[str, str]


# --- Infra Container ---


class AppState(BaseModel):
    """Typed container for infra clients stored on app.state.

    Why a Pydantic model instead of raw dict:
    - Type safety: access via attributes, not string keys
    - Single source of truth for what is stored on app.state
    """

    model_config = {"arbitrary_types_allowed": True}

    pg: PostgresClient
    redis: RedisClient
    s3: S3Client
    llm: MiMo


# --- Lifespan ---


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage infra client lifecycle.

    Startup: create all clients, store on app.state.
    Shutdown: release in reverse order to avoid cascading failures.
    Each release is wrapped in try/except so one failure does not skip others.
    """
    configure_logging()
    log.info("lifespan.startup.begin", env=settings.environment)

    pg = create_postgres_client()
    redis = create_redis_client()
    s3 = create_s3_client()
    llm = create_mimo_provider()

    app.state.deps = AppState(pg=pg, redis=redis, s3=s3, llm=llm)
    log.info("lifespan.startup.complete")

    yield

    # Shutdown: reverse order, each in try/except
    log.info("lifespan.shutdown.begin")
    for name, close_fn in [
        ("llm", llm.aclose),
        ("s3", s3.aclose),
        ("redis", redis.aclose),
        ("pg", pg.aclose),
    ]:
        try:
            await close_fn()
            log.info("lifespan.shutdown.released", client=name)
        except Exception:  # noqa: BLE001 - must not let one failure skip others
            log.exception("lifespan.shutdown.release_failed", client=name)
    log.info("lifespan.shutdown.complete")


# --- FastAPI App ---


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)


# --- Health Endpoints ---


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe - returns 200 if FastAPI process is alive.

    Why separate from /ready:
    - /health = "is the process alive?" (always 200 if we can respond)
    - /ready  = "are all deps healthy?" (may return degraded)
    - K8s uses liveness for restart, readiness for traffic routing
    """
    return HealthResponse()


@app.get("/ready", response_model=ReadyResponse)
async def ready() -> ReadyResponse:
    """Readiness probe - parallel ping of all 4 deps.

    Why returns 200 even when deps fail (not 503):
    - K8s readiness: 200 = "route traffic", non-200 = "do not route"
    - Individual dep status in body lets ops distinguish partial vs full failure
    - A single dep failing should not cause readiness to flap

    Why asyncio.gather instead of sequential:
    - 4 independent health_check() calls, each ~1-5ms network roundtrip
    - Sequential: total = sum(all), ~4-20ms
    - Parallel: total = max(single), ~1-5ms
    """
    deps: AppState = app.state.deps

    pg_ok, redis_ok, s3_ok = await asyncio.gather(
        deps.pg.health_check(),
        deps.redis.health_check(),
        deps.s3.health_check(),
    )

    # LLM probe: no standard ping endpoint exists for LLM APIs
    # Use a trivial chat call; mock provider in tests handles this cheaply
    llm_ok = True
    try:
        resp = await deps.llm.chat(
            [{"role": "user", "content": "ping"}],
            max_tokens=1,
            timeout=5,
        )
        llm_ok = bool(resp.content)
    except Exception:  # noqa: BLE001 - LLM probe failure should not crash /ready
        log.warning("ready.llm_probe_failed")
        llm_ok = False

    status_map = {
        "postgres": "ok" if pg_ok else "fail",
        "redis": "ok" if redis_ok else "fail",
        "s3": "ok" if s3_ok else "fail",
        "llm": "ok" if llm_ok else "fail",
    }
    overall = "ok" if all(v == "ok" for v in status_map.values()) else "degraded"

    log.info("ready.probe_complete", status=overall, deps=status_map)
    return ReadyResponse(status=overall, deps=status_map)
