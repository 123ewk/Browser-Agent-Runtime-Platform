# 没有 Docker 时的开发降级方案

> 适用:本地没装 Docker,但仍要跑 Phase 0 的 LLM / 配置 / 日志部分。

## 范围

- ✅ Pydantic Settings / structlog 日志
- ✅ LLM Provider Mock(不需要真实 API)
- ✅ 单元测试(不需要数据库)
- ❌ 真实 Postgres / Redis / MinIO(必须 Docker)
- ❌ Playwright 浏览器(需 Docker 或本地 chromium)

## 配置

```bash
# 1. 创建 .env
cp .env.example .env
```

把 `.env` 改成:

```ini
# Mock LLM(不需要 Key)
LLM_PROVIDER=mock

# 数据库用 SQLite(需要在 Settings 里加 sqlite 配置)
# 详见"扩展 Settings 支持 SQLite"小节
```

## 扩展 Settings 支持 SQLite(可选)

在 `app/core/config.py` 加一个 `database_url` 属性,优先读 `DATABASE_URL` 环境变量,否则根据 `postgres_*` 拼。

## 跑测试

```bash
uv run pytest -m "not integration"
```

不依赖任何外部服务,只跑 Mock LLM + 内存 Settings。

## 跑应用(部分)

```bash
uv run uvicorn app.main:app --reload
# /health 能用
# /ready 会报告 postgres/redis/s3 不可用,但不阻塞进程
```

## 建议

- 装个 Docker Desktop:Windows / Mac / Linux 全平台有官方支持
- 国内用户:docker-compose 镜像拉取慢,可以用阿里云镜像替换
- 终极方案:WSL2 + Linux Docker Daemon(性能最好)
