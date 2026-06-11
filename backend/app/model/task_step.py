"""TaskStep 模型 —— 不可变审计日志,不是普通业务表。

为什么 immutable(只增不改):
- 步骤是 agent 执行轨迹的审计依据,修改历史等同于伪造记录
- LangGraph 的 state replay 依赖精确的 step 序列,乱改会导致状态恢复错乱
- 业务上不存在"编辑历史步骤"的需求

为什么不在 Task 表的 jsonb 字段里存步骤列表: 步骤量可能很大(一个任务上百步),
独立表可以分页查询并按 step_index 做断点续传。"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.model.task import Task


class TaskStep(Base, UUIDMixin):
    __tablename__ = "task_steps"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # V2.5: 可观测增强 — token/延迟/成本追踪
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 步骤执行耗时
    llm_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)  # LLM 调用延迟
    tokens_prompt: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 输入 token 数
    tokens_completion: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 输出 token 数
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 使用的模型名
    reasoning: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # ReAct 推理文本 (think 步骤)
    step_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="act"
    )  # observe|think|act|human
    dom_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # Worker 提取的 DOM 摘要
    visible_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # Worker 提取的可见文本

    task: Mapped[Task] = relationship(back_populates="steps")
