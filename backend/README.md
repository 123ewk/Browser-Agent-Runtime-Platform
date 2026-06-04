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
```

## Pre-commit 工作流

`.pre-commit-config.yaml` 在 `backend/`(跟 `pyproject.toml` 物理紧贴、内聚)。
git commit 触发 hook 时 cwd = git 根(项目根),所以 **install 必须用 `--config` 显式指 path**,
否则 hook 找不到配置会静默失败。

```bash
# 在 backend/ 目录下(uv sync 之后)
# 一次性安装 git hook
uv run pre-commit install --config backend/.pre-commit-config.yaml

# 手动跑全量校验
uv run pre-commit run --all-files --config backend/.pre-commit-config.yaml

# 跑单个 hook
uv run pre-commit run ruff --config backend/.pre-commit-config.yaml
uv run pre-commit run mypy --config backend/.pre-commit-config.yaml
```

跑通的 hook 链(10 个):

| hook | 作用 |
|---|---|
| pre-commit-hooks v5.0.0 | trailing-whitespace / EOF / yaml / toml / large-files / merge-conflict / private-key |
| ruff-pre-commit v0.7.4 | `--fix --exit-non-zero-on-fix` + format(line-length=100, black 兼容,规则集 E/F/W/I/UP/B/SIM) |
| mirrors-mypy v2.1.0 | `mypy==2.1.0` 跟 `pyproject.toml` 对齐,pydantic plugin 启用,中等严格度(详见 `pyproject.toml` `[tool.mypy]`) |

升级 hook 版本:`uv run pre-commit autoupdate --config backend/.pre-commit-config.yaml`(谨慎,
langchain / openai 这类三方库版本变更可能连带触发 mypy 类型签名变化)。

## 不在 Phase 0 范围

- 业务 service / Skill / Runtime 节点
- 任何 ORM 模型
- 任何前端
- CI / 用户鉴权
