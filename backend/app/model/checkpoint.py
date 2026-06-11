"""Checkpoint 模型 —— append 模式存 checkpoint,不使用 upsert。

为什么 append 而非 update-in-place:
- 保留完整的历史 checkpoint 序列,可以回溯 agent 的决策路径
- 崩溃恢复时只需要取最新一条,旧数据在后续加 TTL 清理即可
- update-in-place 需要额外 where 条件甄别"是不是最新的",比 append 多一次查询

为什么单独建表不塞在 Task jsonb 字段: checkpoint 的 state_data 可能非常大(LangGraph 全状态),
单独放在一张表里可以做大字段单独存储,不影响 Task 表的查询性能。

新增字段说明:
- checkpoint_type: 区分 auto/manual/final/error,便于运维筛选
- schema_version: 独立字段,DB 级查询旧版本 checkpoint,比从 JSONB 解析快
- snapshot_hash: state_data SHA256,崩溃恢复时检测数据损坏
- parent_checkpoint_id: V2 Checkpoint DAG/回滚时使用,V1 为 None
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.model.task import Task


class Checkpoint(Base, UUIDMixin):
    __tablename__ = "checkpoints"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state_data: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # P0 新增字段
    checkpoint_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="auto", index=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # V2.5: 人机协作 — 记录"用户未响应的 ask_human 上下文", resume 时还原到 Trajectory 头部
    pending_ask_human: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    task: Mapped[Task] = relationship(back_populates="checkpoints")
