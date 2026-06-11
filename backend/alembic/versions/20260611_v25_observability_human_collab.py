"""V2.5 可观测增强 + 人机协作 数据迁移

变更:
- task_steps: 9 列 (duration_ms/llm_latency_ms/tokens_prompt/tokens_completion/model_name/reasoning/step_type/dom_summary/visible_text)
- tasks: 3 列 (total_tokens/total_cost_usd/llm_model_used)
- checkpoints: 1 列 (pending_ask_human JSONB)
- agents: status 注释更新 (支持 DRAINED, 无需改列因为 VARCHAR)

索引:
- idx_task_steps_step_type: 按 step_type 过滤 (think/human 步骤查询)
- idx_task_steps_step_type_duration: 步骤耗时百分位查询
- idx_tasks_user_created_at: stats 聚合查询联合索引
- idx_agents_status: agents 状态过滤 (任务创建时校验 agent.status='active')

所有新增列 nullable + 有 DEFAULT (不阻塞现有写路径)。

Revision ID: 4d5e6f7a8b9c
Revises: 3c4d5e6f7a8b
Create Date: 2026-06-11 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4d5e6f7a8b9c"
down_revision: Union[str, Sequence[str], None] = "3c4d5e6f7a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── task_steps: 9 列 (全部 nullable, 不阻塞现有写路径) ──
    op.add_column("task_steps", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.add_column(
        "task_steps", sa.Column("llm_latency_ms", sa.Integer(), nullable=True)
    )
    op.add_column(
        "task_steps", sa.Column("tokens_prompt", sa.Integer(), nullable=True)
    )
    op.add_column(
        "task_steps", sa.Column("tokens_completion", sa.Integer(), nullable=True)
    )
    op.add_column(
        "task_steps", sa.Column("model_name", sa.String(length=64), nullable=True)
    )
    op.add_column("task_steps", sa.Column("reasoning", sa.Text(), nullable=True))
    op.add_column(
        "task_steps",
        sa.Column(
            "step_type",
            sa.String(length=16),
            nullable=False,
            server_default="act",
        ),
    )
    op.add_column(
        "task_steps", sa.Column("dom_summary", sa.Text(), nullable=True)
    )
    op.add_column(
        "task_steps", sa.Column("visible_text", sa.Text(), nullable=True)
    )

    # ── tasks: 3 列 (有 DEFAULT, 不阻塞现有写路径) ──
    op.add_column(
        "tasks",
        sa.Column(
            "total_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "total_cost_usd",
            sa.Numeric(precision=10, scale=6),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "tasks",
        sa.Column("llm_model_used", sa.String(length=64), nullable=True),
    )

    # ── checkpoints: 1 列 ──
    op.add_column(
        "checkpoints",
        sa.Column("pending_ask_human", sa.dialects.postgresql.JSONB(), nullable=True),
    )

    # ── 索引 1: task_steps 按 step_type 过滤 (think/human 步骤查询) ──
    op.create_index(
        "idx_task_steps_step_type",
        "task_steps",
        ["step_type"],
        postgresql_where=sa.text("step_type IN ('think', 'human')"),
    )

    # ── 索引 2: stats 聚合查询联合索引 ──
    op.create_index(
        "idx_tasks_user_created_at",
        "tasks",
        ["user_id", sa.text("created_at DESC")],
    )

    # ── 索引 3: agents 状态过滤 (任务创建时校验 agent.status='active') ──
    op.create_index(
        "idx_agents_status",
        "agents",
        ["status"],
        postgresql_where=sa.text("status = 'active'"),
    )

    # ── 索引 4: task_steps 步骤耗时百分位查询 ──
    op.create_index(
        "idx_task_steps_step_type_duration",
        "task_steps",
        ["step_type", "duration_ms"],
        postgresql_where=sa.text("duration_ms IS NOT NULL"),
    )


def downgrade() -> None:
    # ── 索引 (先删索引再删列, 避免依赖冲突) ──
    # drop_index 只需索引名 + 表名, 不需要 postgresql_where (那是 create_index 的参数)
    op.drop_index("idx_task_steps_step_type_duration", table_name="task_steps")
    op.drop_index("idx_agents_status", table_name="agents")
    op.drop_index("idx_tasks_user_created_at", table_name="tasks")
    op.drop_index("idx_task_steps_step_type", table_name="task_steps")

    # ── checkpoints 列 ──
    op.drop_column("checkpoints", "pending_ask_human")

    # ── tasks 列 ──
    op.drop_column("tasks", "llm_model_used")
    op.drop_column("tasks", "total_cost_usd")
    op.drop_column("tasks", "total_tokens")

    # ── task_steps 列 ──
    op.drop_column("task_steps", "visible_text")
    op.drop_column("task_steps", "dom_summary")
    op.drop_column("task_steps", "step_type")
    op.drop_column("task_steps", "reasoning")
    op.drop_column("task_steps", "model_name")
    op.drop_column("task_steps", "tokens_completion")
    op.drop_column("task_steps", "tokens_prompt")
    op.drop_column("task_steps", "llm_latency_ms")
    op.drop_column("task_steps", "duration_ms")
