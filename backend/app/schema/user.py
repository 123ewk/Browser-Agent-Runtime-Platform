"""用户认证相关的 Pydantic DTO。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    """注册请求体。"""

    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class UserLogin(BaseModel):
    """登录请求体。"""

    username: str
    password: str


class UserOut(BaseModel):
    """用户信息(不含密码)。"""

    id: uuid.UUID
    username: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """登录成功后返回的 JWT。"""

    access_token: str
    token_type: str = "bearer"
