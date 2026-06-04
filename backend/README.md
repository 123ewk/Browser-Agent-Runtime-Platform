# Browser Agent Runtime - Backend

> Phase 0 阶段:后端骨架 + 基础设施 + LLM 调通

## 目录结构

```
backend/
+-- app/                  # 应用代码
|   +-- api/              # HTTP/WS 接口层
|   +-- service/          # 业务逻辑层
|   +-- repository/       # 数据访问层
|   +-- model/            # ORM 模型
|   +-- schema/           # Pydantic DTO
|   +-- core/             # 配置/日志/中间件
|   +-- infra/            # Redis/S3/LLM 客户端
+-- alembic/              # 数据库迁移
+-- tests/                # 测试
+-- docker-compose.yml    # 本地依赖
+-- alembic.ini
+-- pyproject.toml
+-- .env.example
+-- .pre-commit-config.yaml
```

分层规则(api -> service -> repository -> model),禁止反向依赖。

## 开发环境搭建

### 1. 安装依赖(uv 已经在用)

```bash
uv sync
uv run playwright install chromium
```

### 2. 启动基础设施

```bash
docker compose up -d
# 等 healthcheck 全过
docker compose ps
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env,填入 DeepSeek API Key(其他用默认值即可)
```

### 4. 跑 FastAPI

```bash
uv run uvicorn app.main:app --reload
# 健康检查
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

## 常用命令

```bash
# Lint + Format
uv run ruff check .
uv run ruff format .

# 测试
uv run pytest                       # 全跑
uv run pytest -m "not integration"  # 跳过真实 LLM 调用
uv run pytest -m integration        # 真实 LLM(需要 Key)

# 数据库迁移
uv run alembic revision --autogenerate -m "init"
uv run alembic upgrade head
uv run alembic downgrade -1

# Pre-commit
uv run pre-commit install
uv run pre-commit run --all-files
```

## 不在 Phase 0 范围

- 业务 service / Skill / Runtime 节点
- 任何 ORM 模型
- 任何前端
- CI / 用户鉴权
