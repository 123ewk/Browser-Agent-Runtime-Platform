"""SessionService —— 组合 SessionRepository + SessionCache,延迟双删保证一致性。

数据流:
  create:    PG(write) → Redis(write),PG 永远是源 of truth(真实)
  get:       Redis(read) → MISS → PG(read) → Redis(set),Redis 降级不阻塞认证
  delete:    Redis(del) → PG(del) → sleep(0.5) → Redis(del)

为什么单独拆 service 层而非在 Repository 里加缓存:
- Repository 只负责"数据访问",缓存一致性是业务策略
- 延迟双删的 sleep + 重试属于 service 层编排逻辑
- 单测可分别 mock repo 和 cache,独立验证
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime

import structlog

from app.repository.session import SessionRepository
from app.schema.session import SessionDTO
from app.service.session_cache import SessionCache


class SessionService:
    """Session 业务逻辑: PG(源 of truth) + Redis(读缓存) + 延迟双删。"""

    def __init__(self, repo: SessionRepository, cache: SessionCache) -> None:
        self._repo = repo
        self._cache = cache
        self._log = structlog.get_logger(__name__)

    async def create(self, token: str, user_id: uuid.UUID, expires_at: datetime) -> SessionDTO:
        """写 PG → 写 Redis。

        先写 PG(源 of truth),Redis 写入失败不影响登录。
        如果先写 Redis 再写 PG 时崩溃,会留下只有缓存没有 DB 的幽灵 session。
        """
        session = await self._repo.create(token, user_id, expires_at)
        ttl = int(expires_at.timestamp() - datetime.now(UTC).timestamp())
        if ttl > 0:
            try:
                await self._cache.set(session, ttl)
            except Exception:  # noqa: BLE001 - 缓存写失败不阻塞登录
                self._log.warning("session.cache.write_failed", token=token)
        return session

    async def get_by_token(self, token: str) -> SessionDTO | None:
        """先读 Redis → MISS 或异常 → 读 PG → 回写 Redis。

        为什么异常也降级而非抛 500:
        - 脏数据/Redis 超时不等于系统不可用,PG 永远能回答"这个 token 有效吗"
        - 抛 500 会让用户被强制登出,体验比降级到 PG 差得多
        """
        try:
            cached = await self._cache.get(token)
            if cached is not None:
                return cached
        except Exception:  # noqa: BLE001 - Redis 降级不阻塞认证
            self._log.warning("session.cache.read_failed", token=token)

        session = await self._repo.get_by_token(token)
        if session is None:
            return None

        ttl = int(session.expires_at.timestamp() - datetime.now(UTC).timestamp())
        if ttl > 0:
            with contextlib.suppress(Exception):  # 回写失败不影响认证
                await self._cache.set(session, ttl)
        return session

    async def delete(self, token: str) -> None:
        """延迟双删:删缓存 → 删 PG → 后台延迟删缓存。

        为什么用 create_task 而非直接 await sleep:
        - logout 路由调用 delete 后应立即返回 204,不等 500ms
        - 后台任务完成延迟双删,不阻塞请求响应

        为什么延迟 500ms:
        - 大于绝大多数并发读请求完成"读 MISS → 查 PG → 写缓存"的时间
        - 500ms 是业界经验值,覆盖 99.9% 场景

        第二删失败时不重试:
        - 脏缓存最多活一个 TTL(几秒到几分钟),不影响正确性
        - 日志告警,运维观察是否需要调整延迟时间
        """
        await self._cache.delete(token)
        await self._repo.delete(token)

        async def _delayed_second_delete() -> None:
            """后台执行第二次缓存删除。"""
            await asyncio.sleep(0.5)
            try:
                await self._cache.delete(token)
            except Exception:  # noqa: BLE001 - 第二删失败不影响登出
                self._log.warning("session.double_delete.failed", token=token)
            else:
                self._log.info("session.delay_double_delete.complete", token=token)

        asyncio.create_task(_delayed_second_delete())
