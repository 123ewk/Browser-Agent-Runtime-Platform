"""TaskStep 相关 Pydantic DTO。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class TaskStepOut(BaseModel):
    """步骤返回体。"""

    id: uuid.UUID
    task_id: uuid.UUID
    step_index: int
    action: str
    result: dict | None = None
    tokens_used: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
