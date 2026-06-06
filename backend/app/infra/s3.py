"""
============================================================
S3/MinIO 基础设施层 — async session + health check
============================================================

为什么选 aioboto3(而不是 boto3 / minio-py / 其它):

1) boto3(同步)
   - 优:官方 AWS SDK,文档最全,协议兼容最稳
   - 缺:全同步 I/O,需 asyncio.to_thread 包装,阻塞 Event Loop;
     Phase 4 可观测性需要 async 链路追踪(LangSmith / OTel),
     同步包装会断 trace 上下文
   - 命中 §8.1.4 性能不是瓶颈但 async 是硬约束(全项目 async)

2) minio-py
   - 优:MinIO 官方 SDK,原生 async
   - 缺:仅兼容 MinIO,切 AWS S3 / 兼容 S3 的其它对象存储需重写;
     项目定位是"S3 协议通用",不应锁定厂商
   - 命中 §8.1.1 重复造否决(业务专属定制不匹配)

3) aioboto3(本项目选用) ✓
   - 基于 aiobotocore(异步 botocore),boto3 API 1:1 兼容
   - 原生 asyncio,与项目全 async 架构对齐
   - Session/Client 生命周期清晰,aclose 显式释放
   - S3 协议通用(AWS S3 / MinIO / Ceph RGW 等皆可)
   - Phase 1+ 接 LangGraph checkpoint / Phase 2 截图流零适配成本

本模块职责(Phase 0 范围):
- 拼 endpoint + credentials + 创建 S3 client
- health_check(list_buckets,失败仅返回 False 不抛)
- aclose 释放 session + client
- 工厂 create_s3_client() 供 FastAPI lifespan / Depends 注入

不在本模块范围(显式排除):
- 上传/下载/预签名 URL — 业务层(service)封装
- Bucket 自动创建 — 部署脚本/运维侧管理
- 多 bucket 路由 — 业务层按场景选 bucket
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, Protocol

import aioboto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings


class S3Like(Protocol):
    """基础设施层统一协议 — 与 postgres.Database / redis.RedisLike 同形。

    health_check 返回 bool 而非抛异常:Phase 0.10 /ready 端点要并行探活 4 个依赖,
    任何一个挂掉不能让整个 /ready 崩溃(K8s readiness 协议要求始终返 200)。
    aclose 释放资源:session / client 都要在 FastAPI lifespan shutdown 时调。

    注意:Protocol 故意与 postgres.Database 解耦,只在结构上对齐(同名同形),
    不强求 import 共用——infra 层各文件自包含,避免横向耦合。
    """

    async def health_check(self) -> bool: ...
    async def aclose(self) -> None: ...


class S3Client:
    """S3 客户端 —— 持有 aioboto3 Session,对外暴露 health_check / aclose / client。

    构造参数显式注入 session,而非 __init__ 内调 aioboto3.Session():
    - 工厂方法负责"从 settings 拼凭证 + 创 session"
    - 单测可传 mock session,无需 patch settings
    - 边界清晰:client 只管"用 S3 做事",不负责"session 怎么来"

    client 属性通过 asynccontextmanager 暴露 aioboto3 的 S3 client:
    - aioboto3 的 client 必须走 `async with session.client("s3") as client`
    - 业务层不能直接持有 client 实例(生命周期不在自己手里)
    - 通过 get_client() 方法 + asynccontextmanager 安全获取
    """

    def __init__(self, session: aioboto3.Session) -> None:
        self._session = session
        self._log = structlog.get_logger(__name__)

    @asynccontextmanager
    async def get_client(
        self,
    ) -> AsyncGenerator[Any, None]:
        """安全获取 S3 client 的 async context manager。

        业务层用法:
            async with s3_client.get_client() as s3:
                await s3.list_buckets()

        不直接暴露 self._session.client 的原因:
        - aioboto3 的 client 有内部连接池,必须走 async with 确保释放
        - 业务层忘记 close 会泄漏 HTTP 连接,长时间运行触发 Too many open files
        """
        async with self._session.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            region_name=settings.s3_region,
        ) as client:
            yield client

    async def health_check(self) -> bool:
        """轻量探活 —— list_buckets,失败仅返 False 不抛。

        为什么 list_buckets 而非 HEAD bucket:
        - list_buckets 走 S3 最基础的 GET / 协议,任何 S3 兼容存储都支持
        - HEAD bucket 部分 MinIO 旧版本有权限差异(403 vs 404 语义不统一)
        - list_buckets 成功 = "凭证正确 + 网络通 + 服务端响应"三重验证

        返回 bool 而非抛异常的语义:
        /ready 端点要并行探活 4 个依赖(后续 postgres/redis/llm),任何一个失败
        整体 /ready 仍 200 OK,只是 deps.s3="fail" —— K8s readiness 协议。
        抛异常会让 /ready 整个崩溃,违反"始终 200"契约。

        异常兜底边界:catch AiobotocoreError(异步层) + BotoCoreError(同步底层),
        其他异常(代码 bug / asyncio 异常)仍要冒上去,便于开发期发现。
        """
        try:
            async with self.get_client() as client:
                await (
                    client.list_buckets()
                )  # S3 标准接口，查询当前存储服务 (MinIO / 阿里云 OSS) 下所有 Bucket 存储桶列表
        except (BotoCoreError, ClientError) as exc:
            self._log.warning(
                "s3.health_check.failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False
        return True

    async def aclose(self) -> None:
        """释放 session —— FastAPI lifespan shutdown 时调。

        aioboto3 Session 本身无 aclose(),但显式标记清理意图:
        - 后续若有 session 级缓存 / 内部连接引用,在此统一清理
        - 与 postgres.aclose() / redis.aclose() 保持同形接口
        - 当前为 no-op(幂等安全),便于未来扩展
        """
        # aioboto3.Session 无显式 close,client 生命周期由 async with 管理。
        # 此处保留空实现,确保与 Database / RedisLike Protocol 同形。
        pass


def create_s3_client() -> S3Client:
    """工厂方法:从 settings 拼凭证 + 创 session,返回 S3Client。

    不在模块级 `s3 = S3Client(...)` 的原因:
    1. 模块 import 时 settings 尚未就绪(.env 可能未读),污染冷启动
    2. 业务层按需调工厂,生命周期跟 FastAPI Depends / lifespan 对齐
    3. 单测可独立 patch session,无需起真 S3/MinIO

    关键配置:
    - endpoint_url:从 settings.s3_endpoint 读,本地开发指向 MinIO(http://localhost:9000)
    - region:从 settings.s3_region 读,默认 us-east-1(MinIO 兼容)
    - credentials:access_key/secret_key 走 SecretStr 解密,不落日志
    """
    session = aioboto3.Session()
    return S3Client(session)
