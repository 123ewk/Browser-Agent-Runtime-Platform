"""Checkpoint DTO —— 不暴露给用户 API,只在服务内部使用。

为什么没有 create/delete DTO: checkpoint 由 agent 执行引擎自动管理,
不需要手动创建或删除。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class CheckpointOut(BaseModel):
    """Checkpoint 出参 —— state_data 是 LangGraph StateGraph 的全状态快照。"""

    id: uuid.UUID
    task_id: uuid.UUID
    state_data: dict
    created_at: datetime

    model_config = {"from_attributes": True}
