"""Session 相关 Pydantic DTO。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class SessionDTO(BaseModel):
    """会话信息(内部使用,不直接暴露给 API 层)。"""

    token: str
    user_id: uuid.UUID
    expires_at: datetime
