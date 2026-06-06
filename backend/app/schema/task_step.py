"""TaskStep DTO —— 只读 DTO,没有 create/update DTO。

为什么没有 TaskStepCreate/TaskStepUpdate:
步骤由 agent 执行引擎内部写入,不通过 HTTP API 暴露给用户。
TaskStepOut 仅用于前端查看运行日志。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class TaskStepOut(BaseModel):
    """步骤出参 —— tokens_used 为 None 表示步骤尚未完成或 LLM 调用报错。"""

    id: uuid.UUID
    task_id: uuid.UUID
    step_index: int
    action: str
    result: dict | None = None
    tokens_used: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
