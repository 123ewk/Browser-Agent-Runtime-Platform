"""Agent 指标缓存 —— Redis 60s TTL, 减少 Dashboard 轮询的 DB 负载。

Dashboard 5s 轮询 GET /agents → 每次 3 次 DB 聚合查询 (agents + last_task_at + metrics)。
60s 缓存可减少 92% 的 DB 查询 (12 次请求中仅 1 次落 DB)。

失效策略:
- 自然过期: 60s TTL (Dashboard 可见延迟 ≤ 60s, 可接受)
- 主动失效: POST /agents/{id}/pause|resume → 立即失效该 agent
- Task 完成: TimelineRecorder 在 task 终态时失效关联 agent 缓存 (按 agent_id 单点, 不全局)
"""

from __future__ import annotations

import json
import uuid

import structlog

from app.infra.redis import RedisClient

logger = structlog.get_logger(__name__)


class MetricsCache:
    """Agent 指标缓存 —— 封装 Redis 读写操作"""

    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis.client  # raw redis.asyncio.Redis

    def _key(self, agent_id: uuid.UUID) -> str:
        return f"agent_metrics:{agent_id}"

    async def get_agent_metrics(self, agent_id: uuid.UUID) -> dict | None:
        """获取 agent 指标缓存, 未命中返回 None"""
        try:
            raw = await self._redis.get(self._key(agent_id))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            logger.warning(
                "metrics_cache.get_failed",
                agent_id=str(agent_id),
                exc_info=True,
            )
            return None

    async def set_agent_metrics(self, agent_id: uuid.UUID, data: dict, ttl: int = 60) -> None:
        """写入 agent 指标缓存"""
        try:
            await self._redis.setex(self._key(agent_id), ttl, json.dumps(data, default=str))
        except Exception:
            logger.warning(
                "metrics_cache.set_failed",
                agent_id=str(agent_id),
                exc_info=True,
            )

    async def invalidate(self, agent_id: uuid.UUID) -> None:
        """失效单个 agent 的指标缓存 (按 agent_id 单点失效)"""
        try:
            await self._redis.delete(self._key(agent_id))
        except Exception:
            logger.warning(
                "metrics_cache.invalidate_failed",
                agent_id=str(agent_id),
                exc_info=True,
            )
