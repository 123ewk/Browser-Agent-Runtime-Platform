"""FastAPI 应用入口 —— 只做装配,不做业务。

职责:
- import 所有组件(routers / lifespan)
- 创建 FastAPI app
- 装配: include_router + lifespan

路由和 schema 已拆到独立文件:
- app/api/health.py — /health /ready 路由
- app/schema/health.py — 响应 DTO
- app/core/lifespan.py — 生命周期管理
- app/core/state.py — InfraDeps 容器
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.core.config import settings
from app.core.lifespan import lifespan

app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

# 装配路由
app.include_router(health_router)
app.include_router(auth_router)
