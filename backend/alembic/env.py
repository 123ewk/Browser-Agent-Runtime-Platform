"""Alembic 迁移配置 —— 从 Settings 读取 DSN,自动发现模型元数据。

autogenerate 基于 target_metadata 对比引擎中的表与模型定义,生成增量迁移。
pgvector 扩展在首次迁移中手动添加(CREATE EXTENSION IF NOT EXISTS vector)。

为什么用异步引擎 + run_async 而非同步驱动:
项目依赖只有 asyncpg,没有 psycopg2。Alembic 原生不支持 async,
但通过 do_run_migrations + run_async 可以在异步引擎上跑同步迁移逻辑。
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.config import settings
from app.model import Base  # 所有模型继承 Base,metadata 已聚合全部表

config = context.config

# 从 Settings 覆盖 sqlalchemy.url,避免 alembic.ini 硬编码连接信息
password = settings.postgres_password.get_secret_value()
dsn = (
    f"postgresql+asyncpg://{settings.postgres_user}:{password}"
    f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
)
config.set_main_option("sqlalchemy.url", dsn)

target_metadata = Base.metadata

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """离线模式:输出 SQL 到文件,不连数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在给定连接上执行迁移(同步逻辑,由 run_async 调度)。"""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """在线模式:用异步引擎连接数据库,在 run_sync 中执行迁移。"""
    connectable = create_async_engine(dsn, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        # run_sync 把同步迁移逻辑包装到异步连接中执行
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式入口:启动事件循环运行异步迁移。"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
