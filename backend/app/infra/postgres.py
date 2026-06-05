"""
============================================================
Postgres 基础设施层 — async engine + health check
============================================================

为什么选 SQLAlchemy 2.x async + asyncpg(而不是裸 asyncpg / 其它 ORM):

1) 裸 asyncpg
   - 优:零抽象、SQL 透明、性能可控
   - 缺:连接池 / 事务 / 类型注解 / Session 全部要自己写,
     Phase 1+ 引入 Task/Checkpoint/Skill 表后这些"通用设施"每个表重写一遍
   - 命中 §8.1.1 重复造否决条件

2) SQLAlchemy 2.x async + asyncpg(本项目选用) ✓
   - 异步 I/O 友好:AsyncEngine 原生 await,无 callback 套娃
   - 内置连接池:pool_size / max_overflow / pool_pre_ping 一行配置搞定
   - 与 Alembic 无缝整合:Phase 1 直接 alembic revision --autogenerate
   - 类型注解友好:Phase 1+ 用 Mapped[str] 等新式注解
   - 工业级成熟度:Python 生态最广泛使用的 DB 工具,文档/社区/招聘市场

3) Tortoise ORM / SQLModel
   - Tortoise:轻量但社区比 SQLAlchemy 小一个量级,Alembic 不友好
   - SQLModel:在 SQLAlchemy 之上叠 Pydantic,但 async 路径不成熟

结论:本项目要"工业级" + "学生能学到 SQLAlchemy 生态",
SQLAlchemy 2.x async + asyncpg 是唯一合适的选择。

本模块职责(Phase 0.6 范围):
- 拼 DSN + 创建 AsyncEngine(连接池 + pool_pre_ping)
- health_check(SELECT 1,失败仅返回 False 不抛)
- aclose 释放连接池

不在本模块范围(显式排除):
- Session 抽象(AsyncSession / sessionmaker)— Phase 1+
- Alembic 集成 — Phase 1+
- ORM 模型 — Phase 1+
- pgvector 扩展 — Phase 2+
"""

from __future__ import annotations

from typing import Protocol

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings


class Database(Protocol):
    """基础设施层统一协议 — 后续 redis / s3 / kafka 都要实现同样的接口。

    health_check 返回 bool 而非抛异常:Phase 0.10 /ready 端点要并行探活 4 个依赖,
    任何一个挂掉不能让整个 /ready 崩溃(K8s readiness 协议要求始终返 200)。
    aclose 释放资源:连接池 / 客户端都要在 FastAPI lifespan shutdown 时调。
    """

    async def health_check(self) -> bool: ...
    async def aclose(self) -> None: ...


def _build_dsn() -> str:
    """构造 async DSN — 走 postgresql+asyncpg 协议,密码经 SecretStr 解密。

    不在工厂里内联写 f-string 的原因:
    - 单测可独立验 DSN 拼装正确性
    - 复用同一份拼装逻辑(Phase 1 Alembic env.py 也会需要)
    """
    password = settings.postgres_password.get_secret_value()
    return (
        f"postgresql+asyncpg://{settings.postgres_user}:{password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


class PostgresClient:
    """Postgres 客户端 — 持有 AsyncEngine,对外暴露 health_check / aclose。

    构造参数显式注入 engine,而非 __init__ 内调 create_async_engine():
    - 工厂方法负责"从 settings 拼 DSN + create engine"
    - 单测可传 mock engine,无需 patch settings
    - 边界清晰:client 只管"用 engine 做事",不负责"engine 怎么来"
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._log = structlog.get_logger(__name__)

    async def health_check(self) -> bool:
        """轻量探活 — SELECT 1,失败仅返 False 不抛。

        为什么 SELECT 1 而非 pg_isready:
        - pg_isready 是 PG 二进制工具,需本地装 PG 客户端,跨平台差
        - SELECT 1 走实际连接 + 协议握手,等价于"应用层真正能用"
        - pool_pre_ping=True 已做"借连接前 ping",SELECT 1 兜底"引擎本身可用"

        返回 bool 而非抛异常的语义:
        /ready 端点要并行探活 4 个依赖(后续 redis/s3/llm),任何一个失败
        整体 /ready 仍 200 OK,只是 deps.postgres="fail" — K8s readiness 协议。
        抛异常会让 /ready 整个崩溃,违反"始终 200"契约。

        异常兜底边界:仅 catch SQLAlchemyError(数据库相关),其他异常
        (代码 bug / asyncio 异常)仍要冒上去,便于开发期发现。
        """
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            self._log.warning(
                "postgres.health_check.failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False
        return True

    async def aclose(self) -> None:
        """释放连接池 — FastAPI lifespan shutdown 时调。

        不调会泄漏 socket 句柄,K8s / 频繁 reload 场景触发 'Too many open files'。
        幂等:AsyncEngine.dispose() 重复调用安全。
        """
        await self._engine.dispose()


def create_postgres_client() -> PostgresClient:
    """工厂方法:从 settings 拼 DSN + create engine,返回 PostgresClient。

    不在模块级 `pg = PostgresClient(...)` 的原因:
    1. 模块 import 时 settings 尚未就绪(.env 可能未读),污染冷启动
    2. 业务层按需调工厂,生命周期跟 FastAPI Depends / lifespan 对齐
    3. 单测可独立 patch DSN / create_async_engine,无需起真 PG

    关键配置:
    - pool_size / max_overflow:从 settings 读,生产可调
    - pool_pre_ping=True:借连接前 ping,断线重连无感(SQLAlchemy 默认值,
      显式写出来便于排错 + 避免默认值变更的兼容风险)
    """
    engine = create_async_engine(
        _build_dsn(),
        pool_size=settings.postgres_pool_size,
        max_overflow=settings.postgres_max_overflow,
        pool_pre_ping=True,  #  SQLAlchemy 数据库连接池健康检测参数，作用：每次从连接池取出连接前，自动 ping 校验连接是否存活。
    )
    return PostgresClient(engine)
