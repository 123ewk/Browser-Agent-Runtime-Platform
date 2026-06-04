# Architecture v0.1 - Phase 0

> 这是 Phase 0 结束时的架构快照。后续 Phase 增量更新。

## 当前态

Phase 0 只完成了"骨架 + 基础设施客户端接入"。**没有**任何业务逻辑、Skill、Runtime、ORM 模型。

## 目录结构

```
backend/
+-- app/
|   +-- api/              # 空 - Phase 1 才有路由
|   +-- service/          # 空 - Phase 1 才有 service
|   +-- repository/       # 空 - Phase 1 才有 repo
|   +-- model/            # 空 - Phase 1 才有 ORM
|   +-- schema/           # 空 - Phase 1 才有 DTO
|   +-- core/
|   |   +-- config.py     # Settings(Pydantic)
|   |   +-- __init__.py
|   +-- infra/            # Phase 0.6~0.9 填入(用户写)
|   +-- main.py           # FastAPI 启动入口
|   +-- __init__.py
+-- alembic/
|   +-- versions/         # 空
|   +-- env.py            # 默认生成,需改读 Settings
|   +-- script.py.mako
+-- tests/                # 空 - 用户写
+-- docker-compose.yml    # postgres + redis + minio
+-- alembic.ini
+-- pyproject.toml
+-- .env.example
+-- .pre-commit-config.yaml
```

## 依赖拓扑

```
FastAPI app (Phase 1+)
    |
    v
core/config.py (Settings)
    |
    v
infra/* (Phase 0.6~0.9 填入)
    |
    v
Postgres / Redis / MinIO / LLM API
```

## 设计原则

1. **配置只走环境变量**(12-Factor),`Settings` 在 `app/core/config.py` 单点定义
2. **敏感字段全部 `SecretStr`**,日志和异常自动脱敏
3. **基础设施接口先行**:`infra/` 下每个客户端先有 Protocol,后有实现(便于 mock)
4. **LLM Provider 抽象**:`DeepSeekProvider` / `MockProvider` / 未来 `OllamaProvider`,通过工厂切换
5. **分层严格**:`api -> service -> repository -> model`,反向依赖禁止

## 不在 Phase 0

- LangGraph `StateGraph` 节点
- Skill 注册表 / Backend Protocol / BrowserContext 池
- 任何 Task / Checkpoint / Skill 表的 ORM
- 任何前端
- 用户系统 / 鉴权

## 后续 Phase 增量入口

| Phase | 主要新增 |
|---|---|
| 1 | `runtime/backend/playwright_browser.py` + `runtime/skills/base.py` + 简单 task runner |
| 2 | `runtime/states.py` + `runtime/graph.py` + Postgres checkpointer |
| 3 | `runtime/nodes/human_input_gate.py` + WS 协议扩展 |
| 4 | 事件总线 + 前端 Next.js |
| 5 | Redis queue + worker 进程 |
| 6 | Skill 动态加载 + 微代理化 |
| 7 | 三个数据/文档 Skill |
| 8 | E2E + Replay + 文档收口 |
| 9 | Vision fallback + 性能优化 |
