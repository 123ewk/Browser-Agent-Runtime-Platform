"""SessionCache —— Redis 缓存层,只负责 GET/SET/DELETE session。

职责边界:
- 序列化/反序列化 SessionDTO ↔ JSON 字符串
- TTL 由调用方传入,不自行计算
- 不感知业务语义(延迟双删、降级策略等)

为什么 JSON 而非 Redis Hash:
- Hash 读写各一轮(HSET + HGETALL),JSON 一轮 GET/SET
- DTO 仅 3 个字段,JSON 序列化开销可忽略
- TTL 设置 SETEX 一条命令搞定,Hash 需额外 EXPIRE

为什么存 str(uuid) + isoformat(datetime) 而不是 pickle:
- JSON 跨语言可读,生产排障直接用 redis-cli GET 就能看
- pickle 有 RCE 风险,且 Python 版本升级可能反序列化失败
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from app.infra.redis import RedisClient
from app.schema.session import SessionDTO


class SessionCache:
    """Session 的 Redis 缓存操作。"""

    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    # ── 内部: key 命名 + 序列化 ──────────────────────────────

    @staticmethod
    def _key(token: str) -> str:
        return f"session:{token}"

    @staticmethod
    def _serialize(session: SessionDTO) -> str:
        """序列化 SessionDTO → JSON 字符串。"""
        return json.dumps(
            {
                "token": session.token,
                "user_id": str(session.user_id),
                "expires_at": session.expires_at.isoformat(),
            },
        )

    @staticmethod
    def _deserialize(raw: str) -> SessionDTO:
        """反序列化 JSON 字符串 → SessionDTO。"""
        data = json.loads(raw)
        return SessionDTO(
            token=data["token"],
            user_id=UUID(data["user_id"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
        )

    # ── 公开接口 ────────────────────────────────────────────

    async def get(self, token: str) -> SessionDTO | None:
        """从 Redis 获取 SessionDTO。"""
        raw = await self._redis.client.get(self._key(token))
        if raw is None:
            return None
        # decode_responses=False 时 Redis.get 返回 bytes,显式解码
        # mypy: Redis.get 返回类型为 bytes | str,实际配置下一定是 bytes
        return self._deserialize(raw.decode("utf-8") if isinstance(raw, bytes) else raw)

    async def set(self, session: SessionDTO, ttl: int) -> None:
        """将 SessionDTO 存储 Redis 缓存,并设置 TTL。"""
        # TTL 由调用方传入,不自行计算
        # 0 表示永不过期
        if ttl <= 0:
            raise ValueError("ttl must be greater than 0")
        # 序列化 JSON 字符串
        # 从 datetime 转换为 isoformat 字符串
        raw = self._serialize(session)
        await self._redis.client.setex(self._key(session.token), ttl, raw)

    async def delete(self, token: str) -> None:
        """从 Redis 删除 SessionDTO。"""
        await self._redis.client.delete(self._key(token))
