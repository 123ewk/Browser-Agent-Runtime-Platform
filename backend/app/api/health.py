"""健康检查路由 —— /health(存活)和 /ready(就绪)。

什么时候 /ready 返回 degraded 而非 ok:
- 任何一个依赖 health_check 失败 → status=degraded
- 单个依赖失败不应导致就绪探针频繁抖动(K8s readiness 协议)
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Request

from app.core.state import InfraDeps
from app.schema.health import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])
log = structlog.get_logger(__name__)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """存活探针 —— FastAPI 进程存活时返回 200。

    与 /ready 分离:
    - /health = "进程是否存活?"(永远 200)
    - /ready  = "依赖是否健康?"(可能返回 degraded)
    """
    return HealthResponse()


@router.get("/ready", response_model=ReadyResponse)
async def ready(request: Request) -> ReadyResponse:
    """就绪探针 —— 并行探测 4 个依赖的健康状态。

    依赖失败时仍返回 200(而非 503):
    - 响应体中的单项依赖状态让运维区分部分故障与完全故障
    - 单个依赖失败不应导致就绪探针频繁抖动

    为什么用 asyncio.gather:
    - 4 个独立的 health_check,并行总耗时 ≈ 最大值而非求和
    """
    deps: InfraDeps = request.app.state.deps

    pg_ok, redis_ok, s3_ok = await asyncio.gather(
        deps.pg.health_check(),
        deps.redis.health_check(),
        deps.s3.health_check(),
    )

    # LLM 探测: 使用一次极简 chat 调用;mock provider 会廉价处理
    llm_ok = True
    try:
        resp = await deps.llm.chat(
            [{"role": "user", "content": "ping"}],
            max_tokens=1,
            timeout=5,
        )
        llm_ok = bool(resp.content)
    except Exception:  # noqa: BLE001 - LLM 探测失败不应崩溃 /ready
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
