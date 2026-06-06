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
    """bcrypt 哈希 —— 自动生成随机盐,即使同密码两次调用结果也不同。

    为什么不用 passlib: 避免为 3 行代码引入额外依赖,
    passlib 是 Python 第三方密码哈希库，封装了 bcrypt/Argon2/PBKDF2/SHA512 等几十种密码加密算法，做了统一接口封装，是 Python 老牌常用密码工具。
    bcrypt 原生 API 足够清晰。
    """
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """验证密码 —— 对比明文密码与数据库哈希结果。"""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: uuid.UUID) -> str:
    """签发 JWT —— user_id 植入 sub 字段,exp 从 Settings 读取。

    为什么用对称 HS256 而非 RSA: 本项目是单体部署,
    密钥管理简单,HS256 性能更好且无需证书轮换。
    """
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> uuid.UUID | None:
    """解码 JWT,验证失败返 None 而非抛异常。

    为什么返 None 不抛: 调用方(Depends)需要的是"能/不能"二值判断,
    抛异常会让中间件栈捕获,不如 None 直接。"""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        return uuid.UUID(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        return None
