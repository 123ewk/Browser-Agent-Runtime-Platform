"""幂等 seed 脚本 —— 确保至少有一个默认 browser agent。

运行方式:
  python -m app.scripts.seed_agents    # 独立运行(需设置环境变量)
  await seed_default_agent(pg)         # 从 lifespan 调用

幂等性: INSERT ... ON CONFLICT (name) DO NOTHING,重跑不会重复插入。
"""

from __future__ import annotations

import asyncio

import structlog

from app.infra.postgres import PostgresClient

logger = structlog.get_logger(__name__)

_SEED_SQL = """
INSERT INTO agents (id, name, display_name, description, is_default)
VALUES (
  gen_random_uuid(),
  'browser-agent-default',
  'Browser Agent',
  '通用浏览器自动化 Agent',
  TRUE
)
ON CONFLICT (name) DO NOTHING
"""


async def seed_default_agent(pg: PostgresClient) -> None:
    """确保默认 agent 存在(幂等)。

    启动时调用,不阻断 API 启动(失败只记 warning)。
    """
    session = pg.session()
    try:
        from sqlalchemy import text

        await session.execute(text(_SEED_SQL))
        await session.commit()
        logger.info("seed_agents.ok")
    except Exception:
        await session.rollback()
        logger.warning("seed_agents.failed", exc_info=True)
    finally:
        await session.close()


async def _main() -> None:
    """CLI 入口: python -m app.scripts.seed_agents"""
    import os

    # 确保必填环境变量存在(与 tests/conftest.py 同样模式)
    os.environ.setdefault("POSTGRES_PASSWORD", "agent_dev_password")
    os.environ.setdefault("S3_ACCESS_KEY", "minio_admin")
    os.environ.setdefault("S3_SECRET_KEY", "minio_dev_password")
    os.environ.setdefault("LLM_API_KEY", "test-key")

    from app.infra.postgres import create_postgres_client

    pg = create_postgres_client()
    try:
        await seed_default_agent(pg)
    finally:
        await pg.aclose()


if __name__ == "__main__":
    asyncio.run(_main())
