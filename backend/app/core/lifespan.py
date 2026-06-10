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

    # 初始化 CheckpointManager (Phase 1.5 P0: Checkpoint 生命周期管理)
    from app.api.tasks import init_checkpoint_manager

    try:
        init_checkpoint_manager(deps.pg)
        log.info("checkpoint_manager.initialized")
    except Exception:
        log.warning("checkpoint_manager.init_failed", exc_info=True)

    # 初始化 ProcessWatchdog (Phase 1.5: 基于心跳的 Worker 存活监控)
    from app.api.tasks import init_watchdog

    try:
        init_watchdog()
        log.info("watchdog.initialized")
    except Exception:
        log.warning("watchdog.init_failed", exc_info=True)

    # Rehydrate TaskStateManager (2026-06-10 bug 修复):
    # 进程启动时从 DB 重建内存状态,避免 /tasks/{id} 返回 PENDING(默认值)
    from app.api.tasks import get_task_state_manager
    from app.runtime.rehydrate import rehydrate_task_states

    try:
        rehydrated = await rehydrate_task_states(deps.pg, get_task_state_manager())
        log.info("rehydrate.completed", count=rehydrated)
        await get_task_state_manager().start_watchdog()
        log.info("watchdog.started")
    except Exception:
        log.warning("rehydrate.init_failed", exc_info=True)

    # 初始化 PreferenceExtractor (长期记忆: LLM 压缩用户偏好)
    from app.api.preferences import init_preference_extractor

    try:
        init_preference_extractor(deps.llm)
        log.info("preference_extractor.initialized")
    except Exception:
        log.warning("preference_extractor.init_failed", exc_info=True)

    log.info("lifespan.startup.complete")

    yield

    # 关闭: 逆序释放,每个包裹 try/except
    log.info("lifespan.shutdown.begin")

    # 停止 rehydrate watchdog + 进程心跳 watchdog(在释放 pg 之前)
    from app.api.tasks import get_task_state_manager, get_watchdog

    try:
        await get_task_state_manager().stop_watchdog()
    except Exception:
        log.exception("rehydrate_watchdog.stop_failed")

    try:
        wd = get_watchdog()
        if wd is not None:
            await wd.stop()
    except Exception:
        log.exception("process_watchdog.stop_failed")

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
