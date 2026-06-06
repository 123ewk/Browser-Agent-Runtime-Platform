"""Alembic 迁移配置 —— 从 Settings 读取 DSN,自动发现模型元数据。

autogenerate 基于 target_metadata 对比引擎中的表与模型定义,生成增量迁移。
pgvector 扩展在首次迁移中手动添加(CREATE EXTENSION IF NOT EXISTS vector)。
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

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


def run_migrations_online() -> None:
    """在线模式:连接数据库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
