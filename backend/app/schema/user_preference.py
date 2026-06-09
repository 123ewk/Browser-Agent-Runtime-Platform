"""UserPreference DTO —— 偏好创建/更新/出参。

key + content 是核心字段,直接注入 system prompt。
category / source 仅用于前端展示和管理。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PreferenceCreate(BaseModel):
    """创建/更新偏好 —— user_id 从当前登录用户获取"""

    key: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=2000)
    category: str = Field(default="PREFERENCE")
    source: str = Field(default="EXPLICIT")


class PreferenceUpdate(BaseModel):
    """更新偏好 —— 只允许改 content / category / source, key 不可变"""

    content: str = Field(min_length=1, max_length=2000)
    category: str = Field(default="PREFERENCE")
    source: str = Field(default="EXPLICIT")


class PreferenceOut(BaseModel):
    """偏好出参"""

    id: uuid.UUID
    user_id: uuid.UUID
    key: str
    content: str
    category: str
    source: str
    confidence: float
    mention_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RememberRequest(BaseModel):
    """POST /preferences/remember 请求体"""

    content: str = Field(min_length=1, max_length=2000)


class RememberResponse(BaseModel):
    """remember 接口返回提取结果"""

    extracted: list[PreferenceOut]
