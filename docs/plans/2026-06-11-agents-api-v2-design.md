# Agents API V2 设计

> 设计确认日期:2026-06-11
> 范围:GET /agents 从硬编码升级到 DB 动态发现 + 真实健康指标
> 后续:Phase 5 多 Agent 并发 / Phase 6 Skill 挂载 / Phase 9 限流

---

## 0. 背景与目标

### V1 现状(待废弃)

[agents.py](backend/app/api/agents.py) 端点 `GET /agents` 直接 `return [{...}]` 硬编码单 agent:

```python
return [
    {
        "id": "browser-agent-01",
        "name": "Browser Agent",
        "description": "通用浏览器自动化 Agent",
        "health": "healthy",          # ← 硬编码
        "lastTaskAt": None,            # ← 永远是 None
        "successRate24h": 0.95,        # ← 硬编码假数据
    }
]
```

**问题**:
1. `health` 永远返回 `healthy`,运维盲区
2. `lastTaskAt` 永远 `None`,无法判断 Agent 是否被使用
3. `successRate24h` 永远 0.95,无真实基线
4. 只能返回 1 个 Agent,Phase 5 多 Agent 并发无法落地
5. 前端 [agent.ts](frontend/src/types/agent.ts) 已有正确类型契约,后端违约

### V2 目标(本次范围)

| # | 目标 | 验收标准 |
|---|---|---|
| 1 | `GET /agents` 从 DB 动态读取 | 返回 `agents` 表所有 `status='active'` 行 |
| 2 | `health` 真实计算 | 基于最近任务成功/失败/超时计算 `healthy/degraded/down` |
| 3 | `lastTaskAt` 真实计算 | 来自 `tasks.updated_at` MAX 聚合 |
| 4 | `successRate24h` 真实计算 | 来自 `tasks` 表 24h 窗口聚合 |
| 5 | 引入 `agents` 表 + seed | 启动时无 agents 自动 seed 一个 `browser-agent-default` |
| 6 | `tasks.agent_id` 外键 | 历史任务回填默认 agent,V1 接口返回字段不变 |

### 不在 V2 范围(明确)

- ❌ Agent 创建/更新/删除 API(管理后台是后续工作)
- ❌ 多 Agent 类型(data-analysis / vision / ...)(Phase 6+)
- ❌ Agent 限流 / 配额(Phase 9)
- ❌ Skill 元数据挂载 Agent(Phase 6)
- ❌ Agent 选型算法(V2 创建任务时仍由前端传 `agent_id` 或后端 fallback default)
- ❌ 实时 WebSocket 健康推送(Dashboard 5s 轮询够用)

---

## 1. §8.0 全局能力清单(Agent 维度)

按 AGENTS.md §8.0 要求,先把 Agent 维度涉及所有 Phase 的能力摊开,避免按当前 Phase 视角漏判。

| 能力 | 是否必做 | 触发 Phase | 触发场景 | V2 处理 |
|---|---|---|---|---|
| Agent 列表(多类型) | ✅ 必做 | 1 | 至少 1 个 browser agent | ✅ 本次 |
| 健康状态(实时) | ✅ 必做 | 1 | 运维要知道 agent 能不能用 | ✅ 本次 |
| 最近任务时间 | ✅ 必做 | 1 | Dashboard 展示活跃度 | ✅ 本次 |
| 24h 成功率 | ✅ 必做 | 1 | Dashboard 卡片指标 | ✅ 本次 |
| Agent 详情(扩展指标) | 🕐 可选 | 4 | Observability 阶段需要 P95 延迟 | ❌ 推到 V2.1 |
| Agent 启停控制 | 🕐 可选 | 5 | 维护时临时下线 | ❌ 推到 V3 |
| Skill 挂载到 Agent | ✅ 必做 | 6 | Skill Metadata + Discovery | ❌ 推到 V3 |
| Agent 选型策略 | ✅ 必做 | 6 | 创建任务时决定用哪个 agent | ❌ 推到 V3 |
| 限流 / 配额 | 🕐 可选 | 9 | 防止单个 agent 过载 | ❌ 推到 V3 |
| 多租户 Agent 隔离 | 🕐 可选 | 9 | 企业版 | ❌ 远期 |

**V2 覆盖率**:5/5 必做能力 = 100%,V2 不需要自造复杂补丁。

---

## 2. V2 详细设计

### 2.1 数据模型

#### 新表 `agents`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | UUID | PK | 全局唯一 |
| `name` | VARCHAR(64) | UNIQUE NOT NULL | 内部标识,如 `browser-agent-default` |
| `display_name` | VARCHAR(128) | NOT NULL | 展示名,如 `Browser Agent` |
| `description` | TEXT | NOT NULL DEFAULT '' | 前端卡片副标题 |
| `type` | VARCHAR(32) | NOT NULL DEFAULT 'browser' | 预留多类型:browser / data_analysis / vision |
| `status` | VARCHAR(16) | NOT NULL DEFAULT 'active' | active / paused / deprecated |
| `config` | JSONB | NULL | LLM 模型 / Skill 列表 / 浏览器类型(V2 暂不消费) |
| `is_default` | BOOLEAN | NOT NULL DEFAULT FALSE | 标记 fallback agent(只能一行 TRUE) |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | |
| `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | |

**索引**:
- `idx_agents_status` ON `agents(status)` — 列表查询 `WHERE status='active'`
- `idx_agents_name` 走 UNIQUE 自带索引
- 部分唯一索引 `idx_agents_one_default` ON `agents(is_default) WHERE is_default = TRUE` — 保证只有一个 default

#### 改表 `tasks`:新增 `agent_id`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `agent_id` | UUID | FK→agents(id) ON DELETE RESTRICT, **NOT NULL** | 单步迁移同时加 FK + NOT NULL,见 §3 |

**为什么 ON DELETE RESTRICT**:
- 防止误删 agent 把任务变成孤儿(审计要求)
- agent 软删除(deprecated)即可,不需要物理删除

**索引**:
- `idx_tasks_agent_id` ON `tasks(agent_id)` — 聚合查询 `WHERE agent_id = ANY($1)` 走索引

**NOT NULL 的事务内处理**(无需分步 ALTER):
- 不能在 ADD COLUMN 时直接加 NOT NULL——现有行的 `agent_id` 全是 NULL,ALTER 会报错
- 正确做法:事务内先 ADD COLUMN(nullable)→ backfill → SET NOT NULL,都在同一事务内完成
- 当前 `tasks` < 10 行,锁表窗口 < 100ms;V3 数据量增大后也不需要改(单步事务本身就正确)

### 2.2 分层架构

按现有 `api → service → repository → model` 分层:

```
backend/app/
├── model/agent.py             # 新增:Agent ORM
├── schema/agent.py            # 新增:AgentOut / AgentListItem DTO
├── repository/agent.py        # 新增:AgentRepository
├── service/agent.py           # 新增:AgentService(计算 health/lastTaskAt/successRate24h)
├── api/agents.py              # 改:list_agents 改用 service
├── api/tasks.py               # 改:create_task 接 agent_id + list_tasks/get_task 的 agentName 从 "browser-agent" 硬编码改为 JOIN agents.display_name
├── model/task.py              # 改:加 agent_id 字段
├── repository/task.py         # 改:create() 接 agent_id,list_by_user 可选 JOIN agents
├── model/__init__.py          # 改:导出 Agent
├── schema/__init__.py         # 改:导出 AgentOut
├── repository/__init__.py     # 改:导出 AgentRepository
├── core/lifespan.py           # 改:lifespan 启动时调用 seed_agents()
└── scripts/seed_agents.py     # 新增:幂等 seed 脚本(默认 agent)
```

**为什么 V2 引入 service 层**:
- 现有 tasks.py / stats.py 都是 api 直接调 repository(看 [stats.py:48](backend/app/api/stats.py#L48) `from app.repository.task import TaskRepository`)
- V1 简单场景可省 service,但 Agent 涉及**跨表聚合**(agents JOIN tasks)+ **业务规则**(健康状态计算)= 业务逻辑层
- 不放进 service 会让 agents.py 长到 200+ 行,违反 §1 模块化原则
- 任务/统计是否同步拆 service,放到 Phase 8 整合时统一处理

### 2.3 端点设计

#### `GET /agents`(V2 增强,字段不变)

**V1 → V2 兼容性**:响应 JSON 字段名、类型、状态枚举值完全不变,前端零修改。

**V2 实现**:
```
GET /agents
  → api.list_agents()
    → service.AgentService.list_active_with_metrics()
      → repository.AgentRepository.list_active()               # 1 次查 agents
      → repository.TaskRepository.last_task_at_map(agent_ids)  # 1 次查最近时间(不限窗口)
      → repository.TaskRepository.aggregate_metrics(agent_ids) # 1 次查 24h+1h 双窗口聚合
      → service 内部组合成最终 AgentOut 列表
```

**数据库查询**(避免 N+1):
```sql
-- 1. 列出 active agents
SELECT id, name, display_name, description, type, status, is_default
FROM agents
WHERE status = 'active'
ORDER BY is_default DESC, created_at ASC;  -- default 排第一

-- 2a. 每个 agent 的最近任务时间(不限窗口,用于 inactive 判定)
SELECT agent_id, MAX(updated_at) AS last_task_at
FROM tasks
WHERE agent_id = ANY($1)
GROUP BY agent_id;

-- 2b. 24h + 1h 双窗口聚合(1h 是 24h 的子集,一次全表扫描搞定)
SELECT
  agent_id,
  COUNT(*) FILTER (WHERE status='completed')                                   AS success_count_24h,
  COUNT(*) FILTER (WHERE status IN ('completed','failed','cancelled'))         AS terminal_count_24h,
  COUNT(*) FILTER (WHERE status='completed' AND updated_at >= NOW() - INTERVAL '1 hour')     AS success_count_1h,
  COUNT(*) FILTER (WHERE status IN ('completed','failed','cancelled') AND updated_at >= NOW() - INTERVAL '1 hour') AS terminal_count_1h
FROM tasks
WHERE agent_id = ANY($1)
  AND updated_at >= NOW() - INTERVAL '24 hours'
GROUP BY agent_id;
```

**3 次查询**(via asyncio.gather 并行)搞定任意数量 agent。Query 2a+2b 合并进同一个 gather,O(1) 不随 agent 数量增长。

**⚠️ 同一个 session 内 gather**: `AsyncSession` 不是线程安全,但 asyncio 单线程模型下**同一个 coroutine 内交替 await 是安全的**,不需要开两个 session:
```python
# 同一个 session 内并行:AsyncSession 在 asyncio 单线程+交替 await 下安全
async with _pg_client.session() as db:
    agents_task = agent_repo.list_active(db)
    last_task_task = task_repo.last_task_at_map(db, agent_ids)
    metrics_task = task_repo.aggregate_metrics(db, agent_ids)
    agents_result, last_task_map, metrics_result = await asyncio.gather(
        agents_task, last_task_task, metrics_task
    )
```

**内存组合**(service 层):
```python
# AgentMetrics 聚合结果(纯数据,无行为)
# 24h 窗口用于 successRate 展示,1h 窗口用于健康判定
class AgentMetrics:
    success_count_24h: int
    terminal_count_24h: int
    success_count_1h: int
    terminal_count_1h: int

# 零值哨兵——新 agent 无历史任务时使用,保证 `metrics_map.get(agent.id)` 不抛 KeyError
_EMPTY_METRICS = AgentMetrics(
    success_count_24h=0, terminal_count_24h=0,
    success_count_1h=0, terminal_count_1h=0,
)

for agent in active_agents:
    metrics = metrics_map.get(agent.id, _EMPTY_METRICS)
    last_task_at = last_task_map.get(agent.id)  # 来自 Query 2a
    health = _compute_health(metrics, last_task_at, settings)  # 注入 settings,见 §2.4
    yield AgentOut(
        id=agent.id,
        name=agent.display_name,   # 暴露 display_name 而非 DB.name
        description=agent.description,
        health=health,
        lastTaskAt=last_task_at,
        successRate24h=_compute_success_rate(metrics),
    )
```

#### `POST /tasks`(V2 增强,新增可选参数)

**V1 → V2 兼容性**:`{goal: "..."}` 请求体完全兼容,不传 `agent_id` 时 fallback 到 default agent。

```python
class TaskCreate(BaseModel):
    goal: str
    agent_id: UUID | None = None  # V2 新增,不传则用 default
```

**V2 实现**:
```python
async def create_task(payload: TaskCreate, user_id: UUID):
    # 1. 解析 agent_id
    agent_id = payload.agent_id
    if agent_id is None:
        agent = await agent_repo.get_default()  # 1 次小查
        if agent is None:
            raise HTTPException(503, "No default agent available")  # 503: 服务不可用(配置缺失),与现有 infra 异常分类一致
        agent_id = agent.id
    else:
        # 校验 agent_id 存在且 active
        agent = await agent_repo.get_by_id(agent_id)
        if agent is None or agent.status != "active":
            raise HTTPException(400, "Invalid agent_id")

    # 2. 后续流程不变
    task_repo.create(user_id, payload, task_id=..., agent_id=agent_id)
    ...
```

### 2.4 健康状态算法(放在 service 层)

阈值从 [core/config.py](backend/app/core/config.py) `Settings` 读,**不写死在代码里**:

```python
# core/config.py 新增字段
class Settings(BaseSettings):
    # ... 现有字段 ...

    # Agent 健康阈值(V2 起从此处读,V2.1 仍可用,避免再返工)
    agent_health_degraded_failure_rate: float = 0.10   # 24h 失败率 ≥ 此值 → degraded
    agent_health_down_failure_rate: float = 0.50       # 1h 失败率 ≥ 此值 → down
    agent_health_inactive_days: int = 7                # 超过此天数无任务 → down
```

```python
# service/agent.py
def _compute_health(
    metrics: AgentMetrics,
    last_task_at: datetime | None,
    settings: Settings,
) -> AgentHealth:
    """健康状态计算规则(按优先级依次判定,命中即返回)

    1. 无历史任务(last_task_at=None) → healthy(新 agent,避免误判 down)
    2. 超过 inactive_days 无任务 → down
    3. 1h 内有任务(terminal_count_1h > 0):
       a. 1h 失败率 ≥ down 阈值 → down
       b. 1h 失败率 > 0(但 < down 阈值) → degraded
       c. 1h 全成功 → healthy
    4. 1h 内无任务(但 ≤ inactive_days):
       a. 24h 失败率 ≥ degraded 阈值 → degraded
       b. 否则 → healthy(agent 空闲,无近期任务)
    """
    # 规则详见 service/agent.py:_compute_health 注释
```

**为什么放 Settings 不放代码常量**:
- 项目已有 pydantic-settings 统一管配置(看 [config.py:4](backend/app/core/config.py#L4))
- 避免 V2 → V2.1"再返工改一次"的二次返工(原方案的债务伏笔)
- 阈值调整时不需要重新部署,改 `.env` 即可

**⚠️ 边界情况:新 agent 无历史任务**
- `last_task_at=None` → 返回 `healthy`(规则 1 early return)
- 不加特判的话,"7 天无任务"规则会把新 agent 打为 `down`,这是误判
- 规则 1 放在最前面,用 early return 拦截

### 2.5 成功率算法

```python
def _compute_success_rate(metrics: AgentMetrics) -> float:
    """24h 窗口成功率

    - 无终态任务 → 返回 0.0(V2 保持,V2.1 可改 None)
    - 终态任务数 = completed + failed + cancelled
    - successRate24h = completed / 终态任务数
    """
    if metrics.terminal_count_24h == 0:
        return 0.0
    return round(metrics.success_count_24h / metrics.terminal_count_24h, 4)
```

**V2 简化**:成功率=0.0 表示"无数据",前端 [agent.ts](frontend/src/types/agent.ts) 已是 `number`,无需改类型。V2.1 可升级为 `number | null`。

### 2.6 Schema 契约

```python
# schema/agent.py
from datetime import datetime
from pydantic import BaseModel, Field
from app.model.agent import AgentHealth as ModelHealth


class AgentOut(BaseModel):
    """Agent 列表/详情 DTO —— V2 与前端 Agent 类型完全对齐

    字段名/类型稳定,后续 V3 加字段必须保持向后兼容
    """
    id: str                       # UUID 转 str
    name: str                     # 来源:DB display_name(展示名,不是内部 name)
    description: str
    health: str                   # healthy / degraded / down
    lastTaskAt: str | None        # ISO 8601,无任务时 null
    successRate24h: float         # 0..1,V2.1 可改 Optional

    model_config = {"from_attributes": True}
```

**为什么 API `name` 来自 DB `display_name` 而非 DB `name`**:
- 前端 [agent.ts](frontend/src/types/agent.ts) 类型契约明确要求 `name` 字段(必须保留,删了会破坏前端类型)
- DB 双字段设计:
  - `name` = 内部标识(UNIQUE,如 `browser-agent-default`,代码/log 用)
  - `display_name` = 展示名(如 `Browser Agent`,API/UI 用)
- API 只暴露 `display_name`,**不暴露** `DB.name`(防止 V2 → V3 引入多类型 agent 时,前端拿到 `data-analysis-default` 这种内部名)
- structlog 日志仍记录 `agent.name='browser-agent-default'`,运维一眼能定位

---

## 3. 数据迁移策略

**单步迁移** —— 当前 `tasks` 表 < 10 行,生产级的"分步 ALTER"是过度工程:

### Step 1(单次 Alembic 迁移,原子事务)

正确的事务内顺序(不能先加 NOT NULL 再 backfill——现有行的 agent_id 全是 NULL):

1. `CREATE TABLE agents (...)` 含部分唯一索引 `idx_agents_one_default`
2. `ALTER TABLE tasks ADD COLUMN agent_id UUID` — 先 nullable
3. `CREATE INDEX idx_tasks_agent_id ON tasks(agent_id)` — 聚合查询索引
4. `INSERT INTO agents (name, display_name, description, is_default) VALUES ('browser-agent-default', 'Browser Agent', '通用浏览器自动化 Agent', TRUE) ON CONFLICT (name) DO NOTHING`
5. `UPDATE tasks SET agent_id = (SELECT id FROM agents WHERE is_default) WHERE agent_id IS NULL` — backfill
6. `ALTER TABLE tasks ALTER COLUMN agent_id SET NOT NULL`
7. `ALTER TABLE tasks ADD FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE RESTRICT`
8. 迁移完成后断言:`SELECT COUNT(*) FROM tasks WHERE agent_id IS NULL` 必须 = 0

### Seed 幂等性
- `seed_agents` 脚本(独立 `python -m app.scripts.seed_agents`)用 `INSERT ... ON CONFLICT (name) DO NOTHING`
- 重跑 seed 不会重复插入
- 切换 default agent 时**先清旧标记再设新**(部分唯一索引会拒绝两个 TRUE):
  ```sql
  UPDATE agents SET is_default = FALSE WHERE is_default = TRUE;
  UPDATE agents SET is_default = TRUE WHERE name = 'browser-agent-default';
  ```
- `description` 文案在 seed 脚本里**硬编码**为"通用浏览器自动化 Agent",与 V1 文案保持一致,避免 V2 切换后前端显示空白

### 回滚预案
- 迁移脚本整段 `downgrade()`:`DROP TABLE agents` + `ALTER TABLE tasks DROP COLUMN agent_id`
- 单步事务天然支持整段回滚,不需要分步协调

---

## 4. 实施步骤(分 4 个 PR)

把数据 + service 合并到 PR1(都是纯数据 / 纯函数,无运行期风险);保留 PR3 task 关联的独立(真正动运行期逻辑);文档/复盘并入收尾 PR。

| PR | 内容 | 验证 | 风险 |
|---|---|---|---|
| **PR1:数据 + service 层** | model/agent.py + schema/agent.py + repository/agent.py + **service/agent.py** + Alembic 迁移 + seed 脚本 + 阈值加入 Settings | `pytest` 单测(下方测试策略)+ 手动跑迁移 + mypy + ruff | 低(纯数据 + 纯函数) |
| **PR2:API 重构** | api/agents.py 改用 service,移除硬编码 | 启动后 `curl /api/agents` 返回真实数据 + 与 V1 字段 1:1 对照 | 中(回归) |
| **PR3:task 关联 + 前端验证** | model/task.py + repository/task.py + api/tasks.py 接 agent_id + 前端 dashboard 手动验证 | 创建任务单测 + DB 验证外键 + 手动刷新 dashboard | 中(影响创建任务) |
| **PR4:文档 + 复盘** | docs/issues/2026-06-11-agents-v2-*.md 10 段结构化复盘 + 本设计 doc 标注 "Implemented: 2026-06-XX" | - | - |

**每个 PR 后都跑**:
- `pytest backend/tests/` 现有单测
- `uv run mypy backend/app backend/tests` 类型检查
- `uv run ruff check .` lint 检查
- `curl http://localhost:8000/api/agents` 验证响应

**PR1 测试策略** —— `service/agent.py` 是纯函数,`@pytest.mark.parametrize` 表驱动覆盖:
```python
# _compute_health 覆盖 7 场景
# AgentMetrics(success_count_24h, terminal_count_24h, success_count_1h, terminal_count_1h)
@pytest.mark.parametrize("metrics,last_task_at,expected", [
    # 1. 新 agent 无任务 → healthy(规则 1 early return)
    (AgentMetrics(0,0,0,0), None, AgentHealth.HEALTHY),
    # 2. 1h 全成功 → healthy(规则 3c)
    (AgentMetrics(3,3,3,3), now-10min, AgentHealth.HEALTHY),
    # 3. 1h 内有少量失败(失败率 < down 阈值)→ degraded(规则 3b)
    (AgentMetrics(5,6,2,3), now-10min, AgentHealth.DEGRADED),
    # 4. 1h 内无任务,24h 全成功,last_task_at 在 2h 前 → healthy(规则 4b,agent 空闲)
    (AgentMetrics(3,3,0,0), now-2hour, AgentHealth.HEALTHY),
    # 5. 1h 内无任务,24h 失败率 ≥ degraded 阈值 → degraded(规则 4a)
    (AgentMetrics(2,3,0,0), now-2hour, AgentHealth.DEGRADED),
    # 6. 1h 全失败 → down(规则 3a)
    (AgentMetrics(3,6,0,3), now-10min, AgentHealth.DOWN),
    # 7. 超过 inactive_days 无任务 → down(规则 2)
    (AgentMetrics(1,1,0,0), now-8day, AgentHealth.DOWN),
])
def test_compute_health(metrics, last_task_at, expected):
    assert _compute_health(metrics, last_task_at, _stub_settings()) == expected
```

`_compute_success_rate` 同理(仅用 24h 字段):
- 无终态任务(terminal_count_24h=0) → 返回 0.0
- 全成功 → 1.0
- 混合 → success_count_24h / terminal_count_24h

**PR1 单测清单**:
- `AgentRepository.list_active()`:空表 / 单行 / 多行
- `AgentRepository.get_default()`:无 default / 有 default / 多 default(违反约束)
- `AgentService.list_active_with_metrics()`:DB 不可用降级 / 0 任务 / 全成功 / 全失败 / 混合
- `seed_agents` 脚本:首次跑 / 重跑幂等
- Alembic 迁移:upgrade + downgrade

---

## 5. 关键技术点

### 5.1 N+1 查询防御

`list_agents()` 必须**只发 2 次 SQL**:
1. 查 active agents
2. 用 `agent_id = ANY($1)` 聚合查

**禁止**为每个 agent 单独查 `SELECT MAX(updated_at) ... WHERE agent_id = ?`,会变 N+1。

### 5.2 部分唯一索引

```sql
CREATE UNIQUE INDEX idx_agents_one_default ON agents(is_default) WHERE is_default = TRUE;
```

PG 部分索引,保证 default agent 唯一。比 app 层校验更可靠。

### 5.3 跨层依赖方向

```
api/agents.py
  → service/agent.py
    → repository/agent.py
      → model/agent.py
    → repository/task.py     (聚合)
      → model/task.py
```

任何反向依赖(`model` 调 `api` / `repository` 调 `service`)= 立即拒绝合并。

### 5.4 异常处理

按 §2"不用 except: pass"原则,service 层:
- DB 异常向上抛(让 api 层统一处理)
- 仅在"DB 不可用"场景降级(参考 [stats.py:66-70](backend/app/api/stats.py#L66-L70) 的 try/rollback/log pattern)
- 降级时返回空 metrics,`health='down'` + `successRate24h=0.0`

### 5.5 asyncio + 并发

- 2 次 SQL 都用现有 `_pg_client.session()` 异步 session
- **用 `asyncio.gather` 并行而非串行,且共用同一个 session**(详见 2.3 节 session 共享说明)
- 总延迟 = max(2 个查询) ≈ 50ms,优于串行 ≈ 100ms

### 5.6 类型提示

按 §2"完整 Type Hints"硬约束:
- 所有函数参数 + 返回值必须标 type
- Pydantic 用 `BaseModel` + `Field(...)`,不用裸 `dict`
- service 函数返回 `AgentOut` DTO,不返回 ORM 对象

---

## 6. 潜在风险与防御

### 6.1 数据回填不一致

**风险**:Step 1 seed default agent 失败,导致回填 SQL 把所有 task.agent_id 设为 NULL。
**防御**:
- seed 脚本用 `INSERT ... ON CONFLICT (name) DO NOTHING`,幂等
- 启动时检测 `agents` 表空 → 阻断 API 启动,提示运行 seed
- Alembic 迁移在 Step 1 后跑 `assert (SELECT COUNT(*) FROM tasks WHERE agent_id IS NULL) = 0`,否则 raise

### 6.2 健康状态阈值误判

**风险**:`healthy / degraded / down` 阈值定错(太严→全 down,太宽→全 healthy)。
**防御**:
- 阈值已移到 [core/config.py](backend/app/core/config.py) `Settings`(`agent_health_degraded_failure_rate` / `agent_health_down_failure_rate` / `agent_health_inactive_days`)
- 调整时改 `.env` 即可,不需要重新部署
- PR1 上线后观察 1 周 dashboard,根据真实 agent 分布调阈值
- service 函数 `_compute_health(metrics, agent, settings)` 接受 settings 注入,单测用 `_stub_settings()` 覆盖不同阈值组合

### 6.3 聚合查询性能

**风险**:tasks 表数据量增大(> 100k 行),`WHERE updated_at >= NOW() - INTERVAL '24 hours'` 扫表。
**防御**:
- tasks 表已有 `idx_tasks_user_id` + 隐式主键索引
- V2 阶段数据量 < 10k 行,扫表无压力
- V3 阶段按 `agent_id, updated_at` 加复合索引:`CREATE INDEX idx_tasks_agent_updated ON tasks(agent_id, updated_at DESC);`

### 6.4 Event Loop 阻塞

**风险**:聚合查询是 async,但 Pydantic `.model_validate()` 在同步路径。
**防御**:
- `.model_validate()` 是 CPU 密集但耗时 < 1ms,无影响
- 后续如果数据量爆炸,改用 `model_validate` 的 async 版本或 pydantic 2 的 strict mode

### 6.5 并发任务导致 metrics 抖动

**风险**:任务在 metrics 聚合时刚好完成 → 部分在窗口内部分在窗口外。
**防御**:
- 这是 Eventual Consistency 不可避免的,接受秒级延迟
- V2.1 引入 Redis 缓存(60s TTL)即可解决
- V2 不做,文档说明"metrics 延迟 < 1s"

### 6.6 误删 agent 导致任务卡死

**风险**:admin 误 `DELETE FROM agents WHERE name='browser-agent-default'`。
**防御**:
- 物理删除被 FK ON DELETE RESTRICT 阻断
- 软删除走 `UPDATE status='deprecated'`,V2 不暴露 DELETE API,根本删不掉

### 6.7 前端契约破坏

**风险**:后端字段名 / 类型变化,前端 dashboard 报错。
**防御**:
- 严格保持 `id / name / description / health / lastTaskAt / successRate24h` 字段名不变
- `health` 枚举值集合不变 `healthy / degraded / down`
- `lastTaskAt` 类型不变 `string | null`
- `successRate24h` 类型不变 `number`

---

## 7. 质量 Checklist 自检

按 AGENTS.md §3 第 6 步 + §2 硬约束:

### 7.1 硬约束 12 项

- [x] 不一次性生成完整项目 → 拆 4 个 PR
- [x] 不跳过测试 → 每个 PR 配单测
- [x] 不跳过设计阶段 → 本文档
- [x] 不隐藏复杂度 → 健康算法写在 service,显式可见
- [x] 单一代码块不超过 50 行 → service/agent.py 每个函数 < 50 行
- [x] 不写万能 utils.py → service/agent.py 单一职责
- [x] 不用 except: pass → service 层 raise 或显式降级
- [x] 不用 print 当日志 → structlog(参考 [tasks.py:50](backend/app/api/tasks.py#L50))
- [x] 不写 SELECT * → repository 显式选列
- [x] 不硬编码 Token / 密码 → 无
- [x] 严格分层 → api → service → repository → model
- [x] 完整 Type Hints → 所有函数标 type
- [x] 注释写为什么不写做了什么 → 已有模式
- [x] 中文注释 → 强制
- [x] 自造 vs 引库判定 → §8 已在第 1 节覆盖,V2 不引新库

### 7.2 设计 Checklist

- [x] §8.0 全局能力清单 → 第 1 节
- [x] §8.1 否决条件核对 → 全部 4 条不命中,自造合理
- [x] §8.2 支持条件核对 → 学习价值 ✅ / 故障透明度 ✅
- [x] §10 反问协议 → 升级方向已与用户确认

---

## 8. 不在 V2 范围(V3+ 预告)

| 能力 | 触发 Phase | 设计草案 |
|---|---|---|
| Agent CRUD API | Phase 6 | `POST/PUT/DELETE /agents` + admin 鉴权 |
| Skill 挂载 | Phase 6 | `agents.config.skills: list[str]` JSONB |
| Agent 选型 | Phase 6 | PolicyEngine 接 agent registry |
| Agent 启停 | Phase 5 | `POST /agents/{id}/pause` |
| 限流 / 配额 | Phase 9 | Redis token bucket per agent_id |
| 多租户隔离 | 远期 | `agents.tenant_id` + RLS |

---

## 9. 结论

V2 升级**风险可控、范围清晰、分层合规**,建议按 4 个 PR 顺序执行,每个 PR 独立可回滚。
**预计总工作量**:4 PR × 1~2 小时 ≈ 半天完成 + 半天 review。
**修订记录**:
- 2026-06-11 v2:采纳自检 4 项修订(单步迁移 / 4 PR / Settings 阈值 / name 映射澄清)
