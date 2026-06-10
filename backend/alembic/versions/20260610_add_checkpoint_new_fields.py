"""add_checkpoint_type_schema_version_snapshot_hash_parent_id

为 checkpoints 表追加批量字段,支持 CheckpointManager P0 功能:

- checkpoint_type: 区分 auto/manual/final/error, 运维筛选用
- schema_version: 独立字段, DB 级查询旧版本, 比从 JSONB 解析快
- snapshot_hash: state_data SHA256, 崩溃恢复时检测数据损坏
- parent_checkpoint_id: V2 Checkpoint DAG/回滚用, V1 为 None

版本策略: 所有字段都 nullable 或有 default, 旧行不报错。
Revision ID: 2b3c4d5e6f7a
Revises: 4f8a2c1b3d5e
Create Date: 2026-06-10 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "2b3c4d5e6f7a"
down_revision: Union[str, Sequence[str], None] = "4f8a2c1b3d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # checkpoint_type: 枚举类型, default "auto"
    op.add_column(
        "checkpoints",
        sa.Column("checkpoint_type", sa.String(20),
                  nullable=False, server_default="auto"),
    )
    op.create_index("ix_checkpoints_checkpoint_type",
                    "checkpoints", ["checkpoint_type"])

    # schema_version: int, default 1
    op.add_column(
        "checkpoints",
        sa.Column("schema_version", sa.Integer(),
                  nullable=False, server_default="1"),
    )

    # snapshot_hash: state_data 的 SHA256, nullable
    op.add_column(
        "checkpoints",
        sa.Column("snapshot_hash", sa.String(64), nullable=True),
    )

    # parent_checkpoint_id: 指向上一个 checkpoint, nullable
    op.add_column(
        "checkpoints",
        sa.Column("parent_checkpoint_id", postgresql.UUID(as_uuid=True),
                  nullable=True),
    )


def downgrade() -> None:
    op.drop_column("checkpoints", "parent_checkpoint_id")
    op.drop_column("checkpoints", "snapshot_hash")
    op.drop_column("checkpoints", "schema_version")
    op.drop_index("ix_checkpoints_checkpoint_type",
                  table_name="checkpoints")
    op.drop_column("checkpoints", "checkpoint_type")
