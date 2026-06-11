"""add_agents_table + tasks.agent_id FK

V2 Agents API 升级: 从硬编码单 agent 迁移到 DB 驱动的 agents 表。

变更:
- 新建 agents 表(10 列,含部分唯一索引保证单 default)
- tasks 表新增 agent_id FK(ON DELETE RESTRICT)
- seed 默认 agent(browser-agent-default)
- 历史 task 自动回填 default agent

事务内顺序(不可调换):
  先 nullable → seed + backfill → SET NOT NULL + FK。
  不能先加 NOT NULL: 现有 task 的 agent_id 全是 NULL,ALTER 直接报错。

Revision ID: 3c4d5e6f7a8b
Revises: 2b3c4d5e6f7a
Create Date: 2026-06-11 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "3c4d5e6f7a8b"
down_revision: Union[str, Sequence[str], None] = "2b3c4d5e6f7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 新建 agents 表
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), unique=True, nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "type",
            sa.String(32),
            nullable=False,
            server_default="browser",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="active",
        ),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_agents_status", "agents", ["status"])
    # 部分唯一索引: 保证只有一个 default agent
    op.create_index(
        "idx_agents_one_default",
        "agents",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default = TRUE"),
    )

    # 2. tasks 加 agent_id(先 nullable,后面 backfill 完再加 NOT NULL)
    op.add_column(
        "tasks",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("idx_tasks_agent_id", "tasks", ["agent_id"])

    # 3. seed 默认 agent(幂等: INSERT ... ON CONFLICT DO NOTHING)
    op.execute(
        """
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
    )

    # 4. 回填历史 task
    op.execute(
        """
        UPDATE tasks
        SET agent_id = (SELECT id FROM agents WHERE is_default LIMIT 1)
        WHERE agent_id IS NULL
        """
    )

    # 5. 加 NOT NULL + FK(回填完成后才安全)
    op.alter_column("tasks", "agent_id", nullable=False)
    op.create_foreign_key(
        "fk_tasks_agent_id",
        "tasks",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # 6. 断言: 不应该有 NULL agent_id
    # (Alembic 不支持事务内断言,但上面的 UPDATE 是幂等的,且 5 的 NOT NULL 就是最终防线)


def downgrade() -> None:
    op.drop_constraint("fk_tasks_agent_id", "tasks", type_="foreignkey")
    op.drop_index("idx_tasks_agent_id", table_name="tasks")
    op.drop_column("tasks", "agent_id")
    op.drop_index("idx_agents_one_default", table_name="agents")
    op.drop_index("idx_agents_status", table_name="agents")
    op.drop_table("agents")
