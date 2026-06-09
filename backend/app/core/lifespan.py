"""FastAPI 生命周期管理 —— 抽离 main.py,专注启动/关闭。

职责:
- startup:配置日志 → 创建 infra 客户端
- shutdown:逆序释放(单个失败不跳过其他)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.state import create_deps

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """管理基础设施客户端生命周期。

    启动: create_deps → app.state.deps。
    关闭: 逆序释放,单个失败不跳过其他(日志 + continue)。
    """
    configure_logging()
    log.info("lifespan.startup.begin", env=settings.environment)

    deps = await create_deps()
    app.state.deps = deps

    # 初始化 PolicyEngine (Phase 2.1: LLM 策略引擎)
    from app.api.tasks import init_policy_engine

    try:
        init_policy_engine(deps.llm)
        log.info("policy_engine.initialized")
    except Exception:
        log.warning("policy_engine.init_failed", exc_info=True)

    # 初始化 TimelineRecorder (Phase 1.5: 执行轨迹落库)
    from app.api.tasks import init_timeline_recorder

    try:
        init_timeline_recorder(deps.pg)
        log.info("timeline_recorder.initialized")
    except Exception:
        log.warning("timeline_recorder.init_failed", exc_info=True)

    log.info("lifespan.startup.complete")

    yield

    # 关闭: 逆序释放,每个包裹 try/except
    log.info("lifespan.shutdown.begin")
    for name, close_fn in [
        ("llm", deps.llm.aclose),
        ("s3", deps.s3.aclose),
        ("redis", deps.redis.aclose),
        ("pg", deps.pg.aclose),
    ]:
        try:
            await close_fn()
            log.info("lifespan.shutdown.released", client=name)
        except Exception:  # noqa: BLE001 - 不能让单个失败跳过其他
            log.exception("lifespan.shutdown.release_failed", client=name)
    log.info("lifespan.shutdown.complete")
