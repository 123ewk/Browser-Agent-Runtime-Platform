"""Task 相关 Pydantic DTO。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    """创建任务 —— 用户只需提供目标文本。"""

    goal: str = Field(min_length=1, max_length=2000)


class TaskUpdate(BaseModel):
    """更新任务状态/结果。"""

    status: str | None = None
    result: dict | None = None


class TaskOut(BaseModel):
    """任务返回体。"""

    id: uuid.UUID
    user_id: uuid.UUID
    goal: str
    status: str
    result: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    """任务列表分页。"""

    items: list[TaskOut]
    total: int
    limit: int
    offset: int
