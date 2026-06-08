"""InfraDeps —— 基础设施容器,类型化 app.state.deps。

职责:
- 定义 app.state 上存储什么客户端(类型安全)
- 提供 create_deps() 工厂,供 lifespan 装配

为什么不用字典:
- 类型安全:通过属性访问而非字符串键
- 单一真相源:明确哪些客户端已初始化
"""

from __future__ import annotations

from pydantic import BaseModel

from app.infra.llm import ChatLLM, create_llm_provider
from app.infra.postgres import PostgresClient, create_postgres_client
from app.infra.redis import RedisClient, create_redis_client
from app.infra.s3 import S3Client, create_s3_client


class InfraDeps(BaseModel):
    """基础设施客户端容器,存储在 app.state.deps。

    命名约定:Infra(基础设施层)+Deps(依赖),
    与 core/ 层其他模块(config/logging)保持平行,避免被误认为业务类。
    """

    model_config = {"arbitrary_types_allowed": True}

    pg: PostgresClient
    redis: RedisClient
    s3: S3Client
    llm: ChatLLM


async def create_deps() -> InfraDeps:
    """工厂: 创建所有基础设施客户端, 返回 InfraDeps 容器。

    当前 4 个 create_*_client() 均为同步函数, 此处无实际 await 操作。
    async 签名是为 Phase 1 预留(browser.launch() 是异步),
    届时直接 await 即可, 无需改 lifespan 签名。
    """
    pg = create_postgres_client()
    redis = create_redis_client()
    s3 = create_s3_client()
    llm = create_llm_provider()
    return InfraDeps(pg=pg, redis=redis, s3=s3, llm=llm)
