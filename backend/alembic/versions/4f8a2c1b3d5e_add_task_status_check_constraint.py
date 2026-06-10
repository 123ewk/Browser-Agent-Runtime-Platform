"""add_task_status_check_constraint

Revision ID: 4f8a2c1b3d5e
Revises: 1a2a75bf4d91
Create Date: 2026-06-10 10:30:00.000000

为什么这个迁移:
- 2026-06-10 bug 复盘 §3.4: tasks.status 列是 String(20), 无 CHECK 约束,
  任何非 enum 字符串都能写入 DB(如历史残留的非法值),污染前端状态显示。
- 加 DB 层 CHECK 约束作为最后一道防线,即使应用层 TaskRepository 校验
  有 bug 也兜底。
- 同时修正历史脏数据: 把所有不在白名单内的 status 改成 'failed',
  reason 由 result 字段记录(如果有),reason 不可知则使用默认 message。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4f8a2c1b3d5e"
down_revision: Union[str, Sequence[str], None] = "1a2a75bf4d91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 必须与 app/runtime/protocol/types.py TaskState 枚举值同步
# 任何 TaskState 新增/删除都要同步更新这个列表 + CHECK 约束
ALLOWED_TASK_STATUSES: tuple[str, ...] = (
    "pending",
    "running",
    "waiting_confirm",
    "paused",
    "stopping",
    "completed",
    "failed",
    "cancelled",
)


def upgrade() -> None:
    # 1. 修正历史脏数据(把非 enum status 改成 'failed',保留 result 字段)
    #    必须放在 CHECK 约束之前,否则 ALTER TABLE 会失败
    bind = op.get_bind()
    allowed_sql = ", ".join(f"'{s}'" for s in ALLOWED_TASK_STATUSES)
    bind.execute(
        sa.text(
            f"""
            UPDATE tasks
            SET status = 'failed',
                result = COALESCE(result, '{{}}'::jsonb) || jsonb_build_object(
                    'legacy_invalid_status', status,
                    'fixed_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                )
            WHERE status NOT IN ({allowed_sql})
              AND status IS NOT NULL
            """
        )
    )

    # 2. 加 CHECK 约束
    #    使用 raw SQL 而非 op.create_check_constraint 是因为 alembic autogenerate
    #    对 CHECK 约束的检测不完整,手写更稳
    op.execute(
        f"ALTER TABLE tasks ADD CONSTRAINT chk_task_status "
        f"CHECK (status IN ({allowed_sql}))"
    )


def downgrade() -> None:
    # 1. 删 CHECK 约束
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS chk_task_status")
    # 2. 还原历史脏数据(把 fixed 后的 failed 还原回原 status, 从 result 读)
    #    这是 best-effort, 不可恢复(因为原 status 已经丢了)
    #    仅在回滚时执行,生产环境应避免 downgrade
    op.execute(
        """
        UPDATE tasks
        SET status = COALESCE(result->>'legacy_invalid_status', status)
        WHERE result ? 'legacy_invalid_status'
        """
    )
