# Phase 0 设计文档

> 状态:待 review
> 范围:基础准备(后端骨架 + 基础设施 + LLM 调通)
> 后续:Phase 1 起开始写业务逻辑

## 1. Phase 0 目标与范围

**目标**:可运行的后端骨架 + 全部基础设施起来 + LLM 调通 + Playwright 装好 + 测试框架就位。

**范围**:

- 后端目录结构完整搭建(一次性建到位,后续 Phase 只填内容)
- FastAPI 启动 + 健康检查
- 全部基础设施客户端封装(不写业务逻辑)
- LLM Provider 抽象 + DeepSeek 实现
- docker-compose 起 Postgres/Redis/MinIO
- 测试框架就位 + 一个冒烟测试
- 不写 ORM 模型,只配 Alembic

**不在范围**:业务 service、Skill、LangGraph 节点、Task 表、Playwright 代码、任何 UI。

## 2. 依赖清单(写入 `pyproject.toml`)

### Runtime 依赖

- `python = "^3.12"`
- `fastapi = "^0.115"`  — Web 框架
- `uvicorn[standard] = "^0.32"`  — ASGI server
- `pydantic = "^2.9"` +  ` = "^2.6"`  — DTO / 配置
- `sqlalchemy[asyncio] = "^2.0.36"`  — ORM
- `asyncpg = "^0.30"`  — Postgres async 驱动
- `alembic = "^1.14"`  — 迁移
- `redis = "^5.2"`  — Redis 客户端(asyncio 接口)
- `aioboto3 = "^13.3"`  — S3 兼容客户端(MinIO)
- `httpx = "^0.28"`  — LLM HTTP 客户端
- `structlog = "^24.4"`  — 结构化日志
- `python-multipart = "^0.0.20"`  — FastAPI 表单解析
- `tenacity = "^9.0"`  — LLM 重试
- `playwright = "^1.49"`  — 浏览器自动化(Phase 1 才用,Phase 0 先装好环境)
- `langgraph = "^0.2"` + `langgraph-checkpoint-postgres = "^2.0"`  — 装好,Phase 0 只引不写
- `langchain-core = "^0.3"`  — 装好,Phase 0 只引不写

### Dev 依赖

- `pytest = "^8.3"`
- `pytest-asyncio = "^0.24"`
- `pytest-cov = "^6.0"`
- `httpx = "^0.28"`(测试中也用)
- `ruff = "^0.7"`  — Lint + Format(单工具替代 flake8/black/isort)
- `mypy = "^1.13"`  — 静态检查(可选,Phase 4 之后强制)
- `pre-commit = "^4.0"`  — Git hook

## 3. 配置层设计(`app/core/config.py`)

使用 Pydantic Settings,所有配置从环境变量读,默认值只用于**本地开发**,生产环境必须显式注入。

```python
class Settings(BaseSettings):
    # 服务
    app_name: str = "browser-agent-runtime"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

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

    # S3 / MinIO
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket_screenshots: str = "screenshots"
    s3_bucket_files: str = "files"
    s3_region: str = "us-east-1"

    # LLM
    llm_provider: Literal["deepseek", "openai", "mock"] = "deepseek"
    llm_api_key: SecretStr
    llm_base_url: str = "https://api.deepseek.com"
    llm_default_model: str = "deepseek-chat"
    llm_timeout_seconds: int = 30
    llm_max_retries: int = 3

    # 浏览器(Phase 1 用,Phase 0 先预留)
    browser_headless: bool = True
    browser_max_contexts: int = 10
    browser_context_idle_timeout: int = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
```

**关键决策**:

- 敏感字段全部 `SecretStr` 类型,日志输出时自动脱敏
- LLM provider 用枚举 + 工厂模式,Phase 9 加 `OllamaProvider` 不用改 Settings
- 不写 `config.dev.yaml` 之类的二级文件,只用环境变量(12-Factor)

## 4. 日志设计(`app/core/logging.py`)

**格式**:JSON(生产) + 控制台彩色(开发)

**字段**:

- `timestamp`(ISO 8601,UTC)
- `level`
- `event`(语义化事件名,不是 message)
- `logger`
- `task_id` / `thread_id`(从 context 自动注入)
- `request_id`(FastAPI middleware 注入)
- 任意业务字段(用 `logger.bind(...)`)

**关键决策**:

- 用 `structlog` 而不是 `loguru`(后者破坏 JSON handler)
- 写一个 `contextvars` 工具:`bind_task_id / clear_task_id`,每个 task 入口调一次
- FastAPI middleware 注入 `request_id`
- 不写自定义 Filter / Handler,全部走 structlog processor 链

## 5. LLM Provider 抽象(`app/infra/llm.py`)

```python
class LLMProvider(Protocol):
    """Phase 0 最小接口。Phase 2 加 vision / streaming / tool call。"""
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> LLMResponse: ...

class LLMResponse(BaseModel):
    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    raw: dict  # 原始响应,排查用
```

**实现**:

- `DeepSeekProvider`(走 OpenAI 兼容协议)
- `MockProvider`(测试 / 无 Key 时降级,返回固定响应 + 0 token)
- `LLMFactory.create(provider_name, settings)` 工厂函数

**关键决策**:

- 接口保持最小,Phase 2 才加 `tool_calls / stream / response_format`(YAGNI)
- `LLMResponse` 强制带 token 计数,Phase 4 cost tracking 不用重写
- 不引入 `langchain-openai`,直接用 `httpx` 调(避免 LangChain 大版本锁死)

## 6. docker-compose 服务清单

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: agent_dev_password
      POSTGRES_DB: agent_runtime
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck: pg_isready ...

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    ports: ["6379:6379"]
    volumes: [redisdata:/data]
    healthcheck: redis-cli ping

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minio_admin
      MINIO_ROOT_PASSWORD: minio_dev_password
    ports: ["9000:9000", "9001:9001"]
    volumes: [miniodata:/data]
    healthcheck: curl -f http://localhost:9000/minio/health/live
```

**降级方案**:`docs/dev_without_docker.md` 写怎么用 SQLite / 本地文件 / Mock LLM 跑 Phase 0(只为不能装 Docker 的临时情况)。

## 7. `.env.example` 字段

列出所有 `Settings` 字段,值用占位符(`<your-deepseek-key>`)。`.env` 加入 `.gitignore`,`.env.example` 提交进库。

## 8. FastAPI 启动骨架(`app/main.py`)

只挂 3 个端点:

- `GET /health`  — 进程存活
- `GET /ready`  — 依赖探活(postgres / redis / s3 / llm 各自状态)
- `GET /`  — 返回 `{"app": "browser-agent-runtime", "version": "0.0.0", "phase": 0}`

**关键决策**:

- 启动时 `lifespan` 里:`Settings` 校验 → 日志初始化 → 各个 `infra/*` 客户端创建 → 关闭时优雅释放
- `/ready` 各依赖**并行**探活,总超时 5s
- 不挂任何业务路由,留到 Phase 1

## 9. Alembic 初始化

- 配 `alembic.ini` + `alembic/env.py`(读 Settings 的 Postgres URL)
- **不**生成任何 migration,只跑 `alembic init` 初始化目录
- Phase 1 才写第一张表的 migration

## 10. 测试策略

**`tests/conftest.py`**:

- `event_loop_policy` 配 Windows / Linux 兼容
- `settings` fixture:测试环境变量覆盖(`LLM_PROVIDER=mock`)
- `db_session` fixture:每个测试事务回滚(Phase 1 才有表,Phase 0 暂时空)
- `client` fixture:`httpx.AsyncClient` + `ASGITransport`

**冒烟测试** `tests/test_health.py`:

- `test_health_returns_200`
- `test_ready_returns_all_deps_ok`(依赖 docker-compose 起来)
- `test_root_returns_metadata`

**`tests/test_config.py`**:

- 测试 `Settings` 从环境变量正确加载
- 测试 `SecretStr` 不在 `repr` 出现

**`tests/test_logging.py`**:

- 测试 `bind_task_id` 后日志带 task\_id
- 测试 JSON 输出

**`tests/test_llm.py`**:

- `MockProvider` 单元测试
- `DeepSeekProvider` 真实调用(标记 `@pytest.mark.integration`,默认跳过)

## 11. 子任务序列(每个对应一次 commit)

| #    | 任务                                     | commit message                                                 |
| ---- | -------------------------------------- | -------------------------------------------------------------- |
| 0.1  | 初始化 git + README + 改 .gitignore        | `chore: init project with readme and gitignore`                |
| 0.2  | pyproject.toml + uv.lock               | `chore: pin python deps via uv`                                |
| 0.3  | pre-commit + ruff + mypy 配置            | `chore: add pre-commit hooks`                                  |
| 0.4  | `app/core/config.py` + 单测              | `feat(config): pydantic settings with secret masking`          |
| 0.5  | `app/core/logging.py` + 单测             | `feat(logging): structlog with context binding`                |
| 0.6  | `app/infra/postgres.py` + health check | `feat(infra): async postgres engine with health probe`         |
| 0.7  | `app/infra/redis.py` + health check    | `feat(infra): async redis client with health probe`            |
| 0.8  | `app/infra/s3.py` + health check       | `feat(infra): aioboto3 s3 client with health probe`            |
| 0.9  | `app/infra/llm.py` + Mock + DeepSeek   | `feat(infra): llm provider abstraction with deepseek and mock` |
| 0.10 | `app/main.py` + /health /ready /       | `feat(api): bootstrap fastapi with health and ready endpoints` |
| 0.11 | docker-compose.yml + .env.example      | `chore(infra): docker compose for local deps`                  |
| 0.12 | alembic init + 配 env.py                | `chore(db): init alembic for future migrations`                |
| 0.13 | 冒烟测试 + 集成测试                            | `test: smoke tests for health, config, llm mock`               |
| 0.14 | 降级方案文档                                 | `docs: dev setup without docker`                               |
| 0.15 | 沉淀 `docs/architecture.md` v0.1         | `docs: phase 0 architecture snapshot`                          |

## 12. 验收标准

```bash
# 1. 安装
uv sync
uv run playwright install chromium  # 浏览器二进制

# 2. 启动依赖
docker compose up -d
# 等待 healthcheck 全过

# 3. 配置
cp .env.example .env
# 编辑 .env 填 DeepSeek Key

# 4. 跑
uv run uvicorn app.main:app --reload
# 另一终端:
curl http://localhost:8000/ready | jq
# 期望:
# {
#   "status": "ok",
#   "deps": {
#     "postgres": "ok",
#     "redis": "ok",
#     "s3": "ok",
#     "llm": "ok"
#   }
# }

# 5. 测试
uv run pytest -m "not integration"  # 全过
uv run pytest -m integration  # 真实 LLM 调用,可选
```

## 13. 关键假设

- **uv 作为包管理**:lock 速度快、`uv.lock` 跨平台。如果不接受换 poetry。
- **Python 3.12**:对 `asyncio` 改进 + `type` 语法利好。
- **测试用 docker-compose 的库,不另起临时库**:避免 `pytest-postgresql` 之类依赖装环境,直接复用 dev 库(测试用单独 schema)。
- **不引入 OpenTelemetry**:Phase 4 才上,避免 Phase 0 复杂度。
- **Playwright 只装不写代码**:浏览器二进制装好(`playwright install chromium`),代码留到 Phase 1。

## 14. 不在 Phase 0 范围(显式排除)

- 任何 ORM 模型(Phase 1 才有第一张表)
- 任何 service / Skill / Runtime 节点
- 任何前端代码
- GitHub Actions CI(Phase 8 加上,Phase 0 太多噪音)
- 鉴权 / 用户系统(暂不考虑,假设是单机 demo)

## 15. 风险 & 防御

| 风险                                   | 防御                                     |
| ------------------------------------ | -------------------------------------- |
| uv 在 Windows 上兼容性                    | 文档注明如果装不上回落 pip + venv                 |
| docker-compose 在国内拉镜像慢               | 文档给国内镜像替换指引                            |
| DeepSeek API 不稳                      | Mock provider 降级,测试不依赖真实 API           |
| SecretStr 误用 `os.getenv` 泄露          | 强制走 Settings,代码 review 卡               |
| FastAPI lifespan 启动顺序错               | 显式按顺序,各阶段打日志                           |
| `pytest-asyncio` 在不同 event loop 下不稳定 | fixture 显式 `loop_scope="session"` + 文档 |

