"""
============================================================
Redis 基础设施层 — async client + 连接池 + health check
============================================================

为什么选 redis-py>=8.0 的 `redis.asyncio` 命名空间(而不是 aioredis / 其它):

1) aioredis
   - 优:早期 asyncio 生态最常用
   - 缺:已停止维护,redis-py 4.2 起官方吸收了它的异步 API,
     新项目继续用 aioredis 等于"用 fork"——错过 bug fix 与新协议
   - 命中 §8.1.1 重复造否决条件(且平替已"接管")

2) coredis
   - 优:纯 asyncio 实现,延迟低
   - 缺:体量小、连接池/集群实现与 redis-py 不兼容,生态割裂;
     后期接 LangGraph checkpoint(走 redis-py 协议)要再叠适配
   - 命中 §8.1.2 核心领域共识强(Redis 客户端)否决

3) redis-py>=8.0 `redis.asyncio`(本项目选用) ✓
   - 官方维护,与 Redis 新协议同步发布(Redis 7 的 RESP3 / Function 等)
   - 内置异步连接池(ConnectionPool.from_url),max_connections 一行配置
   - 内置重试(>= 5.x 默认开启),与生产"网络抖动"场景对齐
   - LangGraph `AsyncRedisSaver` / `AsyncRedisCache` 等下游都走 redis-py 协议,
     Phase 1+ 接 LangGraph checkpoint 零成本
   - 与 Sentry / OpenTelemetry 生态兼容

本模块职责(Phase 0.7 范围,与 §11 任务表 0.7 对齐):
- 拼 URL + 创建 ConnectionPool(max_connections) + Redis(client)
- health_check(PING,失败仅返回 False 不抛)
- aclose 释放 client + 连接池
- 工厂 create_redis_client() 供 FastAPI lifespan / Depends 注入

不在本模块范围(显式排除):
- Pub/Sub、Streams、Pipeline 包装 — Phase 1+ 业务用到再叠
- Sentinel / Cluster 支持 — Phase 5 任务队列时再切
- 自动 key 命名空间 / TTL 策略 — 业务层各自封装
"""

from __future__ import annotations

from typing import Protocol

import structlog
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from app.core.config import settings


class RedisLike(Protocol):
    """基础设施层统一协议 — 与 app.infra.postgres.Database 同形。

    health_check 返回 bool 而非抛异常:Phase 0.10 /ready 端点要并行探活 4 个依赖,
    任何一个挂掉不能让整个 /ready 崩溃(K8s readiness 协议要求始终返 200)。
    aclose 释放资源:连接池 / 客户端都要在 FastAPI lifespan shutdown 时调。

    注意:Protocol 故意与 postgres.Database 解耦,只在结构上对齐(同名同形),
    不强求 import 共用——infra 层各文件自包含,避免横向耦合。
    """

    async def health_check(self) -> bool: ...
    async def aclose(self) -> None: ...


def _build_url() -> str:
    """构造 redis://[:password@]host:port/db URL —— SecretStr 解密后拼装。

    密码走条件分支的原因:
    - 无密码时不要塞 ":@" 前缀(否则部分客户端会发空 auth 命令,触发 NOAUTH)
    - SecretStr 可能是 None(本地开发 / docker-compose 默认无密码)

    不在工厂内联写 f-string 的原因:
    - 单测可独立验 URL 拼装正确性
    - 复用同一份拼装逻辑(Phase 1+ 接 Sentinel / Cluster 切协议头只改这里)
    """
    auth = ""
    if settings.redis_password is not None:
        auth = f":{settings.redis_password.get_secret_value()}@"
    return f"redis://{auth}{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"


class RedisClient:
    """Redis 客户端 —— 持有 Redis + ConnectionPool,对外暴露 health_check / aclose / client。

    构造参数显式注入 client,而非 __init__ 内调 Redis(connection_pool=...):
    - 工厂方法负责"从 settings 拼 URL + 建池 + 创 client"
    - 单测可传 mock client,无需 patch settings
    - 边界清晰:client 只管"用 Redis 做事",不负责"client 怎么来"

    client 属性暴露给业务层调 GET/SET/HSET/XADD 等 Redis 原生命令:
    - Redis 命令集大且多变(GET/SET/HSET/LPUSH/PUBLISH/XADD/ZADD/...),
      在 RedisClient 上每个都加方法等于"薄代理"——重复造
    - 业务层通过 redis_client.client.get(...) 直接调,跟 redis-py 文档一致
    - 后续 Phase 1+ 接 LangGraph 的 AsyncRedisSaver 也要 raw client,直接给最省事
    """

    def __init__(self, client: Redis) -> None:
        self._client = client
        self._log = structlog.get_logger(__name__)

    @property
    def client(self) -> Redis:
        """暴露底层 redis.asyncio.Redis,业务层按需调原生命令(避免薄代理)。"""
        return self._client

    async def health_check(self) -> bool:
        """轻量探活 —— PING,失败仅返 False 不抛。

        为什么 PING 而非 INFO / CONFIG:
        - PING 走单条 RESP 帧,O(1) 网络往返,延迟最低
        - INFO 会拉整张服务器状态(几十 KB),对 /ready 周期探活太重
        - Redis 7+ 在 cluster 拓扑变更时 PING 也可触发重定向(生产可用)

        返回 bool 而非抛异常的语义:
        /ready 端点要并行探活 4 个依赖(后续 postgres/s3/llm),任何一个失败
        整体 /ready 仍 200 OK,只是 deps.redis="fail" —— K8s readiness 协议。
        抛异常会让 /ready 整个崩溃,违反"始终 200"契约。

        异常兜底边界:仅 catch RedisError 及其所有子类(ConnectionError /
        TimeoutError / ResponseError / AuthenticationError 等),其他异常
        (代码 bug / asyncio 异常)仍要冒上去,便于开发期发现。
        """
        try:
            await self._client.ping()
        except RedisError as exc:
            self._log.warning(
                "redis.health_check.failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False
        return True

    async def aclose(self) -> None:
        """释放 client + 连接池 —— FastAPI lifespan shutdown 时调。

        只关 client 不够:redis-py 8.x 的 Redis.aclose() 内部 await
        connection_pool.disconnect(in_use),但显式再 disconnect 一次
        覆盖"池里还有未归还的连接"边界,幂等且安全。

        不调会泄漏 socket 句柄,K8s / 频繁 reload 场景触发 'Too many open files'。
        """
        await self._client.aclose()
        await self._client.connection_pool.aclose()


def create_redis_client() -> RedisClient:
    """工厂方法:从 settings 拼 URL + 建池 + 创 client,返回 RedisClient。

    不在模块级 `redis_client = RedisClient(...)` 的原因:
    1. 模块 import 时 settings 尚未就绪(.env 可能未读),污染冷启动
    2. 业务层按需调工厂,生命周期跟 FastAPI Depends / lifespan 对齐
    3. 单测可独立 patch URL / ConnectionPool,无需起真 Redis

    关键配置:
    - max_connections:从 settings 读,生产可调
    - decode_responses=False:保留 bytes,支持二进制 value(pickle / protobuf),
      业务层需要 str 时显式 decode(避免隐式转换成本)
    - 默认无 socket_timeout:Phase 0 探活场景连接短,加超时易误判;
      业务层长任务可单独构造带超时的 client
    """
    pool = ConnectionPool.from_url(
        _build_url(),
        max_connections=settings.redis_max_connections,
        decode_responses=False,  # 解码响应,保留 bytes,支持二进制 value(pickle / protobuf)
    )
    return RedisClient(Redis(connection_pool=pool))
