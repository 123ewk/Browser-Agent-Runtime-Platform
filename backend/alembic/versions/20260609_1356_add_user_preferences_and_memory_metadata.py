"""add_user_preferences_and_memory_metadata

Revision ID: 1a2a75bf4d91
Revises: 6dbf55_phase1_initial_tables
Create Date: 2026-06-09 13:56:45.040086
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "1a2a75bf4d91"
down_revision: Union[str, Sequence[str], None] = "6dbf55_phase1_initial_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- user_preferences: 用户长期偏好, 注入 system prompt --
    op.create_table(
        "user_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.String(20), nullable=False, server_default="PREFERENCE"),
        sa.Column("source", sa.String(20), nullable=False, server_default="EXPLICIT"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "key", name="uq_user_preferences_user_key"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_user_preferences_user_id", "user_preferences", ["user_id"])

    # -- preference_history: 偏好变更审计日志 --
    op.create_table(
        "preference_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "preference_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("old_content", sa.Text(), nullable=True),
        sa.Column("new_content", sa.Text(), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["preference_id"], ["user_preferences.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_preference_history_preference_id",
        "preference_history",
        ["preference_id"],
    )

    # -- memories: 加 metadata JSONB 列 --
    op.add_column("memories", sa.Column("metadata", postgresql.JSONB(), nullable=True))

    # -- users: username index 改为 unique (与 ORM model 对齐) --
    op.drop_constraint("users_username_key", "users", type_="unique")
    op.drop_index("ix_users_username", table_name="users")
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.create_index("ix_users_username", "users", ["username"], unique=False)
    op.create_unique_constraint("users_username_key", "users", ["username"])

    op.drop_column("memories", "metadata")
    op.drop_table("preference_history")
    op.drop_table("user_preferences")
