"""用户认证 DTO —— register/login 用不同 DTO 而非复用同一个。

为什么 register(UserCreate)和 login(UserLogin)用不同 DTO:
- 注册有字段校验(用户名[2,64],密码[6,128]),登录不需要重复校验
- 注册时密码非空即可,不需要重复校验长度——错误的密码只会导致 401
- 后续如果加"登录验证码",改 UserLogin 不影响注册逻辑
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    """注册 DTO —— 为什么 min_length/max_length:
    - username 最短 2 避免单字符用户名,最长 64 是因为数据库 varchar(64)
    - password 最短 6(业界常见下限),最长 128(bcrypt 输入上限)
    """

    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class UserLogin(BaseModel):
    """登录 DTO —— 不校验密码长度,让 verify_credentials 统一处理。"""

    username: str
    password: str


class UserOut(BaseModel):
    """用户公开信息 —— 不包含 hashed_password,防止序列化泄露。"""

    id: uuid.UUID
    username: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """JWT 令牌响应 —— 使用 Bearer scheme(标准 Authorization 头)。"""

    access_token: str
    token_type: str = "bearer"
