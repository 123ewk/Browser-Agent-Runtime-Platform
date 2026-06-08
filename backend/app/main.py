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
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.tasks import router as tasks_router
from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers
from app.core.lifespan import lifespan

app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

# 装配异常分类 —— 必须在 include_router 之前注册,
# 否则路由内 raise 的异常落不到 handler(注册顺序敏感)。
register_exception_handlers(app)

# 装配 CORS —— 必须早于 include_router,这样预检(OPTIONS)才能被中间件拦截并放行,
# 否则 FastAPI 会把它路由到具体路径,触发 405。
# allow_credentials=False:本项目用 Authorization: Bearer 头而非 Cookie,不需要 credentials mode。
# Starlette 在 credentials=True 时会拒绝 origin="*",所以即便想放开也必须显式列白名单。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 装配路由
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(tasks_router)

if __name__ == "__main__":
    # pre-commit hook 跑 mypy 时未必在 backend venv 内,uvicorn import 需 type: ignore
    import uvicorn  # type: ignore[import-not-found]

    uvicorn.run(app, host="0.0.0.0", port=8000)
