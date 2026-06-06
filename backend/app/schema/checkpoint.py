"""Checkpoint 相关 Pydantic DTO。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class CheckpointOut(BaseModel):
    """Checkpoint 返回体。"""

    id: uuid.UUID
    task_id: uuid.UUID
    state_data: dict
    created_at: datetime

    model_config = {"from_attributes": True}
