from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 服务
    app_name: str = "browser-agent-runtime"
    environment: Literal["dev", "test", "prod"] = "dev"  # 环境,默认 dev
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # CORS —— 允许跨域调用的前端 origin 列表。
    # 用 JSON 字符串配置(逗号分隔多个),避免在 Pydantic 中再引一个 List[HttpUrl] 解析器。
    # 只列通用本地端口(localhost / 127.0.0.1),不要在本字段放内网 IP,那样会随仓库泄露;
    # 内网/外网域名应通过 .env 覆盖 CORS_ALLOW_ORIGINS。
    cors_allow_origins: str = (
        "http://localhost:3000,"
        "http://localhost:5173,"  # Vite 默认
        "http://127.0.0.1:3000,"
        "http://127.0.0.1:5173"
    )

    # Postgres
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "agent"
    postgres_password: SecretStr  # 必填,无默认
    postgres_db: str = "agent_runtime"
    postgres_pool_size: int = 10
    postgres_max_overflow: int = 20

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: SecretStr | None = None
    redis_db: int = 0
    redis_max_connections: int = 20  # 连接池大小,等价于 Postgres pool_size

    # S3 / MinIO
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket_screenshots: str = "screenshots"
    s3_bucket_files: str = "files"
    s3_region: str = "us-east-1"

    # LLM
    llm_provider: Literal["deepseek", "mimo", "openai", "mock"] = "mimo"
    llm_api_key: SecretStr
    llm_base_url: str = "https://api.xiaomimimo.com/v1"
    llm_default_model: str = "MiMo-V2.5"
    llm_timeout_seconds: int = 30
    llm_max_retries: int = 3

    # JWT - 认证
    jwt_secret_key: SecretStr = SecretStr("dev-jwt-secret-change-in-production")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440 * 30  # 30 天

    # 浏览器(Phase 1 用,Phase 0 先预留)
    browser_headless: bool = True
    browser_max_contexts: int = 10
    browser_context_idle_timeout: int = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # 不区分大小写,默认 False
        extra="ignore",  # 忽略额外的环境变量,默认 raise
    )


# 模块级单例:业务代码统一 `from app.core.config import settings` 拿,避免每次都重新实例化。
# 实例化时机:首次 import 时,会读 .env + 环境变量。测试由 tests/conftest.py 提前注入必填 secrets。
settings = Settings()
