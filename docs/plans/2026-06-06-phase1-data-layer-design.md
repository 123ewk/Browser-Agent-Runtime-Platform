# Phase 1 数据层设计

> 设计确认日期:2026-06-06
> 范围:ORM 模型 + Repository + 用户认证(注册/登录)
> 后续:Phase 1 后半段开始 Browser Agent 核心

## 分层架构

```
api/        → 路由(直接调用 repository,Phase 1 暂不拆 service)
schema/     → Pydantic DTO
repository/ → 数据访问层(CRUD,接收 AsyncSession,返回 DTO)
model/      → SQLAlchemy ORM 模型
infra/      → PostgresClient(现有,提供 async_session 工厂)
```

严格单向依赖:api → repository → model,反向禁止。

## 表设计

### User

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID, PK | |
| username | str(64), unique, not null | 登录名 |
| hashed_password | str, not null | bcrypt 哈希 |
| created_at | datetime, not null | |

### Session

| 字段 | 类型 | 说明 |
|------|------|------|
| token | str(128), PK | JWT token |
| user_id | UUID, FK→User, not null | |
| expires_at | datetime, not null | |

### Task

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID, PK | |
| user_id | UUID, FK→User, not null | |
| goal | text, not null | 用户原始目标 |
| status | Enum(PENDING/RUNNING/WAITING_USER/COMPLETED/FAILED/CANCELLED) | |
| result | jsonb, nullable | 最终结构化结果 |
| created_at | datetime, not null | |
| updated_at | datetime, not null | |

### TaskStep

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID, PK | |
| task_id | UUID, FK→Task, not null | |
| step_index | int, not null | 第几步 |
| action | str, not null | 执行的动作描述 |
| result | jsonb, nullable | 动作结果 |
| tokens_used | int, nullable | LLM Token 消耗 |
| created_at | datetime, not null | |

### Checkpoint

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID, PK | |
| task_id | UUID, FK→Task, not null | |
| state_data | jsonb, not null | 序列化的 Agent 状态 |
| created_at | datetime, not null | |

### Memory

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID, PK | |
| user_id | UUID, FK→User, not null | |
| session_id | str, nullable | 关联的会话 |
| content | text, not null | 记忆内容 |
| embedding | vector(1024), nullable | 向量嵌入 |
| created_at | datetime, not null | |

Memory 表只建结构 + pgvector 扩展,写入/查询逻辑留到 Phase 2+。

### Skill

不建表。走本地文件系统(`./skills/`目录),开箱即用、可 Git 版本管理。

## 表关系

```
User ──1:N── Session
User ──1:N── Task ──1:N── TaskStep
                  ──1:N── Checkpoint
User ──1:N── Memory (by session)
```

## Repository 接口

### UserRepository
- `create(username, hashed_password) → UserDTO`
- `get_by_username(username) → UserDTO | None`
- `get_by_id(id) → UserDTO | None`

### SessionRepository
- `create(user_id, expires_at) → SessionDTO`
- `get_by_token(token) → SessionDTO | None`
- `delete(token) → None`

### TaskRepository
- `create(user_id, goal) → TaskDTO`
- `get_by_id(id) → TaskDTO | None`
- `list_by_user(user_id, status=None, limit=20, offset=0) → list[TaskDTO]`
- `update_status(id, status, result=None) → TaskDTO`

### TaskStepRepository
- `create(task_id, step_index, action, result=None, tokens_used=None) → TaskStepDTO`
- `list_by_task(task_id) → list[TaskStepDTO]`

### CheckpointRepository
- `create(task_id, state_data) → CheckpointDTO`
- `get_latest_by_task(task_id) → CheckpointDTO | None`
- `delete_by_task(task_id) → None`

### MemoryRepository
预留占位,Phase 2+ 实现。

## 开发顺序

1. `model/` — 6 个 ORM 模型 + Alembic 迁移(pgvector 扩展)
2. `schema/` — 对应的 Pydantic DTO
3. `repository/user.py` + `test_user.py`
4. `repository/session.py` + `test_session.py`
5. `repository/task.py` + `task_step.py` + `checkpoint.py` + 测试
6. `api/auth.py` — 注册/登录 + JWT 中间件 + 测试

## 关键技术点

- **密码哈希**:bcrypt(FastAPI 的 `password_context`)
- **UUID 主键**:SQLAlchemy 2.x `sa.UUID` + `uuid.uuid4()`
- **pgvector**:迁移脚本 `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`
- **Repository 构造**:接收 `AsyncSession`,不直接依赖 `PostgresClient`
- **JWT**:python-jose 或 PyJWT,FastAPI `Depends` 注入
