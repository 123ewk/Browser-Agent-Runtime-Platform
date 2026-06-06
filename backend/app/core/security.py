"""认证工具 —— 密码哈希 + JWT 签发/验证。

密码用 bcrypt 哈希,不在数据库存明文。
JWT 用 HS256 算法,secret 来自 Settings。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    """bcrypt 哈希密码,自动生成随机盐。"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """验证密码是否匹配哈希。"""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: uuid.UUID) -> str:
    """签发 JWT —— 用户 ID 植入 sub 字段。"""
    payload = {
        "sub": str(user_id),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> uuid.UUID | None:
    """解码 JWT 返回 user_id,验证失败返 None 而非抛异常。"""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        return uuid.UUID(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        return None
