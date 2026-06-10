"""Checkpoint DTO —— 不暴露给用户 API,只在服务内部使用。

为什么没有 create/delete DTO: checkpoint 由 agent 执行引擎自动管理,
不需要手动创建或删除。

state_data 使用 FullCheckpointState 系列 schema 标准化:
- TaskStateSchema: 任务级状态
- StepStateSchema: 步骤级状态
- WorkerRuntimeSchema: Worker 运行时状态(仅序列化可恢复的部分)
- MemoryStateSchema: 推理/记忆状态
- CheckpointMetaSchema: 元数据(version/type/时间)
- FullCheckpointState: 完整 state_data 结构

design decision:
- Worker 的 browser_session / DOM 等无法跨进程恢复的状态不纳入 schema
- 只存"重建 TaskContext + 恢复 PolicyEngine 决策连续性"所需的最小状态集
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CheckpointOut(BaseModel):
    """Checkpoint 出参 —— state_data 是 LangGraph StateGraph 的全状态快照。"""

    id: uuid.UUID
    task_id: uuid.UUID
    state_data: dict
    checkpoint_type: str = "auto"
    schema_version: int = 1
    snapshot_hash: str | None = None
    parent_checkpoint_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════
# state_data 标准化 schema
# ═══════════════════════════════════════════════════════════════


class TaskStateSchema(BaseModel):
    """Task 级状态 —— 用于 Resume 时重建 TaskContext"""

    task_id: str = ""
    status: str = "pending"
    goal: str = ""  # 原始用户目标
    current_subgoal: str = ""  # 当前子目标描述
    current_step_index: int = 0  # 已完成的 step 数
    completed_steps: list[str] = Field(default_factory=list)  # 已完成的 action 列表
    max_steps: int = 20


class StepStateSchema(BaseModel):
    """Step 级状态 —— 当前执行断点信息"""

    current_action: str = ""  # 当前正在执行的动作类型
    action_result: str = ""  # 上一步执行结果摘要
    action_url: str | None = None  # 操作后的页面 URL
    page_title: str | None = None  # 页面标题
    extracted_data: dict[str, Any] = Field(default_factory=dict)  # 提取的结构化数据


class WorkerRuntimeSchema(BaseModel):
    """Worker Runtime 状态 —— 可在新 Worker 中恢复的部分

    不包含 browser_session_id / tab_id / DOM snapshot:
    - Playwright 进程级对象无法跨进程序列化
    - DOM snapshot 在 Resume 瞬间已过时,需要 Worker 重新 navigate
    """

    browser_storage_state: dict[str, Any] | None = None  # Playwright storageState


class MemoryStateSchema(BaseModel):
    """Memory 状态 —— PolicyEngine 决策连续性所需的上下文"""

    trajectory_summary: str = ""  # Trajectory.summary_for_prompt() 结果
    retrieved_knowledge: list[str] = Field(default_factory=list)  # 已检索的知识
    reasoning_context: str = ""  # 当前推理上下文
    user_preferences: list[dict[str, str]] = Field(default_factory=list)


class CheckpointMetaSchema(BaseModel):
    """元数据 —— 版本 + 类型 + 血缘"""

    schema_version: int = 1
    checkpoint_type: str = "auto"  # "auto" | "manual" | "final" | "error"
    created_at: str = ""
    parent_checkpoint_id: str | None = None


class FullCheckpointState(BaseModel):
    """完整的 state_data 结构 —— 所有子 schema 的根容器

    版本策略:
    - version=1 起始,只新增字段不删改
    - 旧 checkpoint 缺失字段时,model_validate 会使用 Field(default)
      自动填充,无需迁移代码
    """

    version: int = 1
    task: TaskStateSchema = Field(default_factory=lambda: TaskStateSchema())
    step: StepStateSchema = Field(default_factory=lambda: StepStateSchema())
    memory: MemoryStateSchema = Field(default_factory=lambda: MemoryStateSchema())
    meta: CheckpointMetaSchema = Field(default_factory=lambda: CheckpointMetaSchema())
    worker: WorkerRuntimeSchema = Field(default_factory=lambda: WorkerRuntimeSchema())
