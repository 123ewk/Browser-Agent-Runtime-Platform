"""Schema 层 —— Pydantic DTO,API 请求/响应格式。

禁止反向依赖:api → service → repository → model。
"""

from app.schema.checkpoint import CheckpointOut
from app.schema.health import HealthResponse, ReadyResponse
from app.schema.task import (
    TaskCreate,
    TaskListResponse,
    TaskMessageCreate,
    TaskMessageOut,
    TaskOut,
    TaskUpdate,
)
from app.schema.task_step import TaskStepOut
from app.schema.user import TokenResponse, UserCreate, UserLogin, UserOut
from app.schema.user_preference import (
    PreferenceCreate,
    PreferenceOut,
    PreferenceUpdate,
    RememberRequest,
    RememberResponse,
)

__all__ = [
    "HealthResponse",
    "ReadyResponse",
    "UserCreate",
    "UserLogin",
    "UserOut",
    "TokenResponse",
    "TaskCreate",
    "TaskUpdate",
    "TaskOut",
    "TaskMessageCreate",
    "TaskMessageOut",
    "TaskListResponse",
    "TaskStepOut",
    "CheckpointOut",
    "PreferenceCreate",
    "PreferenceOut",
    "PreferenceUpdate",
    "RememberRequest",
    "RememberResponse",
]
