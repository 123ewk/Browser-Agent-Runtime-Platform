# Browser Agent Runtime Platform — 后端接口文档

> 基于代码自动生成，最后更新：2026-06-09
> Base URL: `http://localhost:8000`
> 认证方式：Bearer Token（JWT），除 `/health`、`/ready`、`/auth/register`、`/auth/login` 外均需认证

---

## 目录

1. [健康检查](#1-健康检查)
2. [认证](#2-认证)
3. [任务](#3-任务)
4. [Agent 列表](#4-agent-列表)
5. [用户偏好](#5-用户偏好)
6. [Dashboard 统计](#6-dashboard-统计)
7. [通用说明](#7-通用说明)

---

## 1. 健康检查

### GET /health

存活探针 —— 进程存活即返回 200。

**认证**：不需要

**响应**：

```json
{
  "status": "ok"
}
```

---

### GET /ready

就绪探针 —— 并行探测 Postgres / Redis / S3 / LLM 四个依赖的健康状态。

**认证**：不需要

**响应**：

```json
{
  "status": "ok",
  "deps": {
    "postgres": "ok",
    "redis": "ok",
    "s3": "ok",
    "llm": "ok"
  }
}
```

| 字段 | 说明 |
|---|---|
| `status` | `"ok"` = 全部依赖健康；`"degraded"` = 至少一个依赖失败 |
| `deps.*` | 单项依赖状态：`"ok"` 或 `"fail"` |

> 即使有依赖失败也返回 200，通过 `status` 字段区分部分故障与完全故障，避免 K8s readiness 探针频繁抖动。

---

## 2. 认证

### POST /auth/register

注册新用户，创建后自动登录返回 JWT。

**认证**：不需要

**请求体**：

```json
{
  "username": "string (2-64字符)",
  "password": "string (6-128字符)"
}
```

**成功响应** `201 Created`：

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

**错误响应**：

| 状态码 | 说明 |
|---|---|
| `409 Conflict` | 用户名已被占用 |
| `422 Unprocessable Entity` | 请求体校验失败 |

---

### POST /auth/login

用户登录，验证凭据后返回 JWT。

**认证**：不需要

**请求体**：

```json
{
  "username": "string",
  "password": "string"
}
```

**成功响应** `200 OK`：

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

**错误响应**：

| 状态码 | 说明 |
|---|---|
| `401 Unauthorized` | 用户名或密码错误 |
| `422 Unprocessable Entity` | 请求体校验失败 |

---

### POST /auth/logout

注销当前会话，删除服务端 Session 记录。

**认证**：需要 Bearer Token

**成功响应** `204 No Content`（无响应体）

---

## 3. 任务

### POST /tasks

创建并启动一个浏览器自动化任务。

**认证**：需要 Bearer Token

**请求体**：

```json
{
  "goal": "string (1-2000字符，任务目标描述)"
}
```

**成功响应** `200 OK`：

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "state": "running"
}
```

| 字段 | 说明 |
|---|---|
| `task_id` | UUID 格式，任务唯一标识 |
| `state` | 任务初始状态，创建后立即为 `"running"` |

**任务状态流转**：

```
PENDING → RUNNING → COMPLETED
                  → FAILED
                  → STOPPING → CANCELLED
```

---

### GET /tasks

分页查询当前用户的任务列表。

**认证**：需要 Bearer Token

**查询参数**：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `page` | int | 1 | 页码（≥1） |
| `pageSize` | int | 20 | 每页条数（1-100） |
| `status` | string | null | 按状态筛选（可选） |
| `search` | string | null | 搜索关键词（可选） |

**成功响应** `200 OK`：

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "goal": "打开百度搜索Python",
      "agentName": "browser-agent",
      "status": "completed",
      "createdAt": "2026-06-09T10:30:00",
      "updatedAt": "2026-06-09T10:35:00",
      "costUsd": 0
    }
  ],
  "total": 42,
  "page": 1,
  "pageSize": 20
}
```

---

### GET /tasks/{task_id}

查询指定任务的状态。

**认证**：需要 Bearer Token

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 任务 UUID |

**成功响应** `200 OK`：

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "state": "running",
  "reason": "开始执行: 打开百度搜索Python"
}
```

---

### GET /tasks/{task_id}/timeline

获取任务步骤时间线（独立拉取，非 WebSocket）。

**认证**：需要 Bearer Token（仅返回当前用户所属任务的步骤）

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 任务 UUID |

**成功响应** `200 OK`：

```json
[
  {
    "id": "step-uuid",
    "index": 0,
    "kind": "tool",
    "title": "navigate",
    "summary": "导航到 https://www.baidu.com",
    "startedAt": "",
    "durationMs": 1200,
    "tokens": 150
  }
]
```

| 字段 | 说明 |
|---|---|
| `kind` | 步骤类型：`"tool"`（浏览器操作）或 `"observe"`（观察/错误） |
| `title` | Worker action 类型（navigate/click/input_text/screenshot/extract/scroll 等） |

> 非当前用户的任务返回空列表 `[]`。

---

### WS /tasks/{task_id}/ws

WebSocket 事件流 —— 前端 Timeline 的实时数据源。

**认证**：通过 query param 传递 JWT token

**连接地址**：

```
ws://localhost:8000/tasks/{task_id}/ws?token=eyJhbGciOiJIUzI1NiIs...
```

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 任务 UUID |

**Query 参数**：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `token` | string | 是 | JWT access_token |

**服务端推送事件格式**（RuntimeEvent）：

```json
{
  "event": "STEP_COMPLETE | ERROR | TASK_FINISHED",
  "task_id": "550e8400-...",
  "payload": { ... }
}
```

| 事件类型 | 说明 |
|---|---|
| `STEP_COMPLETE` | 单步执行完成 |
| `ERROR` | 执行出错 |
| `TASK_FINISHED` | 任务结束（completed/failed/cancelled） |

**心跳**：服务端每 60 秒发送 `{"type": "heartbeat"}` 保持连接。

**连接关闭码**：

| Code | 说明 |
|---|---|
| `4001` | Token 无效或已过期 |

---

## 4. Agent 列表

### GET /agents

列出当前可用的 Agent。

**认证**：不需要

**成功响应** `200 OK`：

```json
[
  {
    "id": "browser-agent-01",
    "name": "Browser Agent",
    "description": "通用浏览器自动化 Agent",
    "health": "healthy",
    "lastTaskAt": null,
    "successRate24h": 0.95
  }
]
```

> V1 返回单个静态 Browser Agent，V2 将从 DB/Redis 动态发现 Agent 实例。

---

## 5. 用户偏好

### GET /preferences

全量返回当前用户的偏好列表，用于 system prompt 构造。

**认证**：需要 Bearer Token

**成功响应** `200 OK`：

```json
[
  {
    "id": "pref-uuid",
    "user_id": "user-uuid",
    "key": "preferred_language",
    "content": "中文",
    "category": "PREFERENCE",
    "source": "EXPLICIT",
    "confidence": 0.95,
    "mention_count": 3,
    "created_at": "2026-06-09T10:00:00",
    "updated_at": "2026-06-09T10:00:00"
  }
]
```

---

### POST /preferences

创建或更新偏好（基于 user_id + key 做 upsert）。

**认证**：需要 Bearer Token

**请求体**：

```json
{
  "key": "string (1-128字符)",
  "content": "string (1-2000字符)",
  "category": "PREFERENCE",
  "source": "EXPLICIT"
}
```

| 字段 | 默认值 | 说明 |
|---|---|---|
| `category` | `"PREFERENCE"` | 偏好分类 |
| `source` | `"EXPLICIT"` | 来源标记 |

**成功响应** `201 Created`：

```json
{
  "id": "pref-uuid",
  "user_id": "user-uuid",
  "key": "preferred_language",
  "content": "中文",
  "category": "PREFERENCE",
  "source": "EXPLICIT",
  "confidence": 1.0,
  "mention_count": 1,
  "created_at": "2026-06-09T10:00:00",
  "updated_at": "2026-06-09T10:00:00"
}
```

---

### DELETE /preferences/{pref_id}

删除指定偏好。

**认证**：需要 Bearer Token

**路径参数**：

| 参数 | 类型 | 说明 |
|---|---|---|
| `pref_id` | UUID | 偏好记录 ID |

**成功响应** `204 No Content`（无响应体）

**错误响应**：

| 状态码 | 说明 |
|---|---|
| `404 Not Found` | 偏好记录不存在 |

---

### POST /preferences/remember

用户说"记住:xxx"，LLM 压缩提取后自动写入偏好。

**认证**：需要 Bearer Token

**请求体**：

```json
{
  "content": "string (1-2000字符，自然语言描述)"
}
```

**成功响应** `200 OK`：

```json
{
  "extracted": [
    {
      "id": "pref-uuid",
      "user_id": "user-uuid",
      "key": "preferred_browser",
      "content": "Chrome",
      "category": "PREFERENCE",
      "source": "EXPLICIT",
      "confidence": 0.9,
      "mention_count": 1,
      "created_at": "2026-06-09T10:00:00",
      "updated_at": "2026-06-09T10:00:00"
    }
  ]
}
```

> LLM 从自然语言中提取结构化偏好（key + content），逐条 upsert 写入数据库。

---

## 6. Dashboard 统计

### GET /stats/dashboard

Dashboard 顶部统计聚合。

**认证**：需要 Bearer Token

**查询参数**：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `window` | string | `"24h"` | 统计窗口，可选值：`1h` / `24h` / `7d` / `30d` |

**成功响应** `200 OK`：

```json
{
  "window": "24h",
  "tasksToday": 12,
  "tasksTodayDeltaPct": 0,
  "running": 2,
  "successRate": 0.85,
  "tokensToday": 0,
  "tokensTodayDeltaPct": 0,
  "costTodayUsd": 0,
  "estimatedMonthlyCostUsd": 0,
  "agents": []
}
```

| 字段 | 说明 |
|---|---|
| `tasksToday` | 窗口内创建的任务数 |
| `tasksTodayDeltaPct` | 较上期变化百分比（V1 返回 0，无历史基线） |
| `running` | 当前运行中的任务数 |
| `successRate` | 终态任务中 completed 的比例 |
| `tokensToday` | 窗口内消耗的 token 数（V1 返回 0） |
| `costTodayUsd` | 窗口内花费（V1 返回 0） |
| `estimatedMonthlyCostUsd` | 月度预估花费（V1 返回 0） |
| `agents` | Agent 级别统计（V1 返回空数组） |

---

## 7. 通用说明

### 认证方式

除标记为"不需要"的接口外，所有请求必须在 Header 中携带：

```
Authorization: Bearer <access_token>
```

Token 通过 `/auth/register` 或 `/auth/login` 获取，有效期 30 天（配置项 `jwt_expire_minutes`）。

### 通用错误响应格式

```json
{
  "detail": "错误描述信息"
}
```

### 常见 HTTP 状态码

| 状态码 | 说明 |
|---|---|
| `200` | 成功 |
| `201` | 创建成功 |
| `204` | 成功（无响应体） |
| `400` | 请求参数错误 |
| `401` | 未认证或 Token 无效 |
| `404` | 资源不存在 |
| `409` | 资源冲突（如用户名重复） |
| `422` | 请求体校验失败 |
| `500` | 服务器内部错误 |
| `503` | 依赖服务不可用（如数据库未连接） |

### CORS 配置

默认允许的前端 Origin：

- `http://localhost:3000`
- `http://localhost:5173`（Vite 默认）
- `http://127.0.0.1:3000`
- `http://127.0.0.1:5173`

可通过环境变量 `CORS_ALLOW_ORIGINS` 覆盖。
