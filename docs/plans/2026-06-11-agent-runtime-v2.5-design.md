# Agent Runtime V2.5 设计

> 设计日期: 2026-06-11
> 范围: ReAct 决策引擎 + 用户中途插话 + Agent 可观测增强 + Agent 启停控制
> 前置: V2.0 (agents 表 + 真实健康指标 + task 关联) 已完成

---

## 0. 背景与目标

### V2.0 现状

V2.0 完成了 agents 表 + 真实健康指标 + task 关联。但核心决策引擎仍是简单 PolicyEngine,缺少闭环推理和人机协作能力:

**问题**:
1. PolicyEngine 只做 `(goal + trajectory) → next action`,无观察→思考→行动循环 — 遇到复杂页面(登录/验证码/支付)无法自主判断
2. 用户无法在任务执行中插话 — ChatInput 在 RUNNING 状态被禁用,用户必须等任务结束或手动暂停
3. 无 token/延迟/成本追踪 — 仪表盘 tokensToday/costTodayUsd 硬编码为 0
4. Agent 无法启停控制 — 没有 pause/resume API,维护时只能改 DB 手动设 status
5. NEED_CONFIRM 事件已定义但 Worker 从未发射,WAITING_CONFIRM 状态闲置

### V2.5 目标

| # | 目标 | 验收标准 |
|---|---|---|
| 1 | ReAct 决策引擎 | PolicyEngine → ReActEngine,输出 Observe→Think→Act 循环,Timeline 可见推理过程 |
| 2 | 用户中途插话 | RUNNING 状态可发送消息,Agent 暂停并重新规划 |
| 3 | 人机协作(Agent 求助) | 遇到登录/验证码等阻塞 → NEED_HUMAN → WAITING_USER → 用户响应后继续 |
| 4 | Agent 可观测增强 | token 消耗 / LLM 延迟 / 步骤耗时 / 成本追踪, stats 改用 SQL 聚合 |
| 5 | Agent 启停控制 | POST /agents/{id}/pause|resume, paused agent 拒绝新任务 |

### 不在 V2.5 范围(明确)

- ❌ ActionPlanner / GoalChecker / ActionRiskEvaluator(V3 决策管道)
- ❌ 多 Skill 类型(data_analysis / pdf_generator)(Phase 6)
- ❌ Vision Fallback / LangGraph 集成(远期)
- ❌ 多 Agent 并发(Phase 5)
- ❌ Agent 选型策略(Phase 6)
- ❌ 限流 / 配额(Phase 9)

---

## 1. §8.0 全局能力清单(Runtime 维度)

按 AGENTS.md §8.0 要求,先把 Runtime 维度涉及的能力摊开,避免按当前 Phase 视角漏判。

| 能力 | 是否必做 | 触发 Phase | 触发场景 | V2.5 处理 |
|---|---|---|---|---|
| ReAct 决策(观察→思考→行动) | ✅ 必做 | 2.5 | Agent 需要在动态网页中自主推理 | ✅ 本次 |
| Agent 求助人类(阻塞检测) | ✅ 必做 | 2.5 | 登录/验证码/支付确认无法自动处理 | ✅ 本次 |
| 用户中途插话(中断+重规划) | ✅ 必做 | 2.5 | 用户想中途改变方向或补充指令 | ✅ 本次 |
| Token/延迟/成本追踪 | ✅ 必做 | 2.5 | 可观测性基础,简历亮点 | ✅ 本次 |
| Agent 启停控制 | ✅ 必做 | 2.5 | 维护时临时下线,不影响现有任务 | ✅ 本次 |
| 步骤耗时百分位(P50/P95) | 🕐 可选 | 4 | Observability 深度指标 | ✅ 本次(低额外成本) |
| Agent 时间序列指标 | 🕐 可选 | 4 | Dashboard 趋势图 | ✅ 本次(低额外成本) |
| Vision Fallback | ✅ 必做 | 7 | selector 失效时截图分析 | ❌ 推到 V3 |
| ActionPlanner(多步规划) | ✅ 必做 | 6 | 复杂目标分解 | ❌ 推到 V3 |
| GoalChecker(目标判定) | ✅ 必做 | 6 | 目标是否达成的精确判定 | ❌ 推到 V3 |

**V2.5 覆盖率**: 7/10 必做能力 = 70%。V3 补上 ActionPlanner/GoalChecker/Vision。

---

## 2. 总体架构变更

```
V2.0:
  PolicyEngine.decide(goal, trajectory) → action
  Worker: START → 执行 → 等 CONTINUE → 执行 → ... → STOP
  状态机: 8 状态(PENDING..CANCELLED)
  前端: ChatInput 在 RUNNING 时禁用

V2.5:
  ReActEngine.decide(goal, trajectory, observation) → ACT | ASK_HUMAN | DONE
  Worker: +INTERRUPT/PAUSE/RESUME 命令
  状态机: +WAITING_USER(人机等待)
  前端: ChatInput 在 RUNNING 时可输入, NEED_HUMAN 时弹窗
  数据: +token/延迟/成本字段
```

### 分层影响

```
backend/app/
├── api/agents.py              # 改: +detail/metrics/pause/resume 端点
├── api/tasks.py               # 改: _run_task 改用 ReActEngine + message 增强
├── api/stats.py               # 改: Python 过滤→SQL 聚合
├── service/agent.py           # 改: +详细指标计算 + Redis 缓存集成
├── service/cost.py            # 新增: LLM 成本计算(纯函数)
├── service/metrics_cache.py   # 新增: Redis 60s TTL 指标缓存
├── runtime/react_engine.py    # 新增: ReAct 决策引擎(替代 PolicyEngine)
├── runtime/policy_engine.py   # 保留: 作为 LLM 失败时的 fallback
├── runtime/protocol/types.py  # 改: +EventType/CommandType/TaskState/ReActDecisionType
├── runtime/protocol/schemas.py # 改: +新 payload 类型
├── runtime/protocol/transitions.py # 改: +WAITING_USER 转换
├── runtime/protocol/constants.py # 改: PROTOCOL_VERSION → "2.5"
├── runtime/timeline_recorder.py # 改: +think/observe/human 步骤订阅
├── repository/task.py         # 改: +时间序列聚合 + 延迟百分位 + 成本聚合
├── repository/task_step.py    # 改: +token 聚合 + 步骤耗时百分位
├── model/task.py              # 改: +total_tokens/total_cost_usd/llm_model_used
├── model/task_step.py         # 改: +7 个新列
├── core/lifespan.py           # 改: init_react_engine 替代 init_policy_engine
└── worker/worker_session.py   # 改: +INTERRUPT/PAUSE/RESUME 命令分发
```

---

## 3. 协议层变更(Protocol V2.5)

### 3.1 EventType

```python
class EventType(StrEnum):
    # --- V1 保留 ---
    WORKER_READY = "WORKER_READY"
    WORKER_HEARTBEAT = "WORKER_HEARTBEAT"
    STEP_START = "STEP_START"
    STEP_COMPLETE = "STEP_COMPLETE"
    SCREENSHOT = "SCREENSHOT"
    PROGRESS = "PROGRESS"
    NEED_CONFIRM = "NEED_CONFIRM"         # 保留: 风险确认(should I do X?)
    ERROR = "ERROR"
    TASK_FINISHED = "TASK_FINISHED"
    TASK_STATE_CHANGED = "TASK_STATE_CHANGED"
    COMMAND_ACK = "COMMAND_ACK"
    WATCHDOG_TIMEOUT = "WATCHDOG_TIMEOUT"

    # --- V2.5 新增 ---
    THINK_START = "THINK_START"           # ReAct 思考阶段开始
    THINK_COMPLETE = "THINK_COMPLETE"     # ReAct 思考完成(含 reasoning 文本)
    OBSERVE_COMPLETE = "OBSERVE_COMPLETE" # 页面观察完成
    NEED_HUMAN = "NEED_HUMAN"             # Agent 能力边界(login/captcha/paywall)
    HUMAN_RESPONSE = "HUMAN_RESPONSE"     # 用户已回复 Agent
    INTERRUPTED = "INTERRUPTED"           # Worker 已被中断
    RESUMED = "RESUMED"                   # Worker 已从中断恢复
```

**NEED_HUMAN vs NEED_CONFIRM 区别**:
- `NEED_CONFIRM`: 系统已经知道下一步,但需要用户批准(高风险操作:"是否发布?")
- `NEED_HUMAN`: 系统无法继续,需要人类提供能力(登录凭据/验证码/人工判断)

### 3.2 CommandType(激活 V2 预留)

```python
class CommandType(StrEnum):
    # V1
    START = "START"
    CONTINUE = "CONTINUE"
    REJECT = "REJECT"
    STOP = "STOP"

    # V2.5 激活
    INTERRUPT = "INTERRUPT"   # Runtime→Worker: 立即中断当前动作
    PAUSE = "PAUSE"           # Runtime→Worker: 完成当前步骤后暂停
    RESUME = "RESUME"         # Runtime→Worker: 从暂停恢复
```

### 3.3 TaskState

```python
class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"   # 风险确认等待
    WAITING_USER = "waiting_user"         # V2.5 新增: 等待人类输入(Agent求助 或 用户中断)
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

### 3.4 ReActDecisionType

```python
class ReActDecisionType(StrEnum):
    ACT = "ACT"            # 执行下一步浏览器动作
    ASK_HUMAN = "ASK_HUMAN"  # 阻塞,需要人类介入
    DONE = "DONE"          # 目标已达成
```

### 3.5 状态转换表

```python
_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.PENDING: {TaskState.RUNNING},
    TaskState.RUNNING: {
        TaskState.WAITING_CONFIRM,
        TaskState.WAITING_USER,      # V2.5 新增
        TaskState.PAUSED,
        TaskState.STOPPING,
        TaskState.FAILED,
        TaskState.COMPLETED,
    },
    TaskState.WAITING_CONFIRM: {
        TaskState.RUNNING,
        TaskState.STOPPING,
        TaskState.FAILED,
    },
    TaskState.WAITING_USER: {        # V2.5 新增
        TaskState.RUNNING,           # 用户响应,继续
        TaskState.STOPPING,          # 用户取消
        TaskState.FAILED,
    },
    TaskState.PAUSED: {
        TaskState.RUNNING,
        TaskState.STOPPING,
        TaskState.FAILED,
    },
    TaskState.STOPPING: {TaskState.CANCELLED},
}
```

### 3.6 新增/修改 Payload

```python
# THINK_COMPLETE 事件 payload
class ThinkCompletePayload(BaseModel):
    step_index: int
    reasoning: str              # 完整推理文本(Timeline 展示用)
    decision: str               # "ACT" | "ASK_HUMAN" | "DONE"
    confidence: float = 1.0
    tokens_used: int = 0        # 本次 LLM 调用消耗的 token

# NEED_HUMAN 事件 payload
class NeedHumanPayload(BaseModel):
    block_type: str             # login | captcha | paywall | consent | other
    question: str               # 问用户的问题
    context_url: str | None = None
    screenshot_key: str | None = None  # S3 key,前端展示截图

# OBSERVE_COMPLETE 事件 payload
class ObserveCompletePayload(BaseModel):
    step_index: int
    url: str | None = None
    title: str | None = None
    dom_summary: str = ""       # 压缩后的 DOM/页面文本
    visible_text: str = ""      # 页面可见文本(前 2000 字符)

# INTERRUPT 命令 payload
class InterruptPayload(BaseModel):
    reason: str                 # "user_interrupt"
    user_message: str = ""      # 用户说了什么

# StepCompletePayload 扩展字段
class StepCompletePayload(BaseModel):
    # ... V1 字段 ...
    duration_ms: int | None = None      # V2.5: 步骤执行耗时
    step_type: str = "act"              # V2.5: observe|think|act|human
    reasoning: str = ""                 # V2.5: think 步骤的推理文本

# DecisionResponse 扩展字段
class DecisionResponse(BaseModel):
    # ... V1 字段(skill, action, reasoning, is_terminal) ...
    decision_type: str = "ACT"          # V2.5: ACT|ASK_HUMAN|DONE
    confidence: float = 1.0             # V2.5
    tokens_used: int = 0                # V2.5
    model_used: str = ""                # V2.5
    llm_latency_ms: int = 0             # V2.5
```

---

## 4. ReAct 决策引擎

### 4.1 设计原则

- **替代 PolicyEngine** 作为默认引擎(PolicyEngine 保留作为 LLM 失败时的 fallback)
- **Observe → Think → Act** 三阶段,每阶段独立事件发布(Timeline 可见)
- **决策类型**: ACT(下一步动作) | ASK_HUMAN(能力边界) | DONE(目标达成)
- **LLM 失败时 fallback 链**: ReActEngine LLM 失败 → PolicyEngine.decide() → regex URL 提取

### 4.2 ReActEngine 类

```python
# runtime/react_engine.py

class ReActEngine:
    """ReAct 决策引擎: Observe → Think → Decide

    与 PolicyEngine 的区别:
    - PolicyEngine: (goal + trajectory) → next action(纯反应式)
    - ReActEngine:   (goal + trajectory + page_state) → reasoning → decision(认知式)

    decision 有三种:
    - ACT: 执行浏览器动作(同 PolicyEngine)
    - ASK_HUMAN: 遇到登录/验证码等阻塞,需要人类介入
    - DONE: 目标已达成(is_terminal=True)
    """

    def __init__(
        self,
        llm: ChatLLM,
        event_bus: EventBus,
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 800,  # 比 PolicyEngine 多 300: 推理文本需要更多 token
        react_timeout: float = 30.0,  # LLM 超时(秒)
    ) -> None: ...

    async def decide(
        self,
        goal: str,
        trajectory: Trajectory,
        observation: ObservationState,  # 页面状态快照
        preferences: list | None = None,
    ) -> DecisionResponse:
        """完整 Observe→Think→Decide 管道

        1. Observe: 收集上下文 → 发布 OBSERVE_COMPLETE
        2. Think: LLM 推理 → 发布 THINK_START → THINK_COMPLETE
        3. Decide: 映射 ThinkResult → DecisionResponse
        """
```

### 4.3 ObservationState(页面状态快照)

```python
@dataclass
class ObservationState:
    """当前页面状态 —— ReAct 的"观察"输入"""
    url: str | None = None
    title: str | None = None
    dom_summary: str = ""       # 压缩后的 DOM/可见文本(前 3000 字符)
    recent_errors: list[str] = None  # 最近 3 个错误消息
    step_index: int = 0
```

Worker 在 `STEP_COMPLETE` 事件中携带 `url`/`title`(已实现),新增 `dom_summary` 字段由 BrowserSkill 在每次导航后提取。

### 4.4 ReAct System Prompt

```
You are a browser automation agent using the ReAct (Reasoning + Acting) framework.

## CURRENT OBSERVATION
- URL: {url}
- Page Title: {title}
- Page Content Summary: {dom_summary}

## GOAL
{goal}

## EXECUTION HISTORY
{trajectory_summary}

## USER PREFERENCES
{user_preferences}

## INSTRUCTIONS
Think step by step:
1. OBSERVE: What do you see on the current page? Is it relevant to the goal?
2. REASON: What should be the next step? Are there any blockers?
3. DECIDE: Choose ONE of the following:

**ACT**: Execute a browser action. Output:
{"decision":"ACT","action":{"type":"navigate|click|input_text|screenshot|extract","target":"...","value":"...","description":"..."},"reasoning":"I see X, therefore I should do Y"}

**ASK_HUMAN**: You cannot proceed without human help (login required, captcha, paywall, ambiguous choice). Output:
{"decision":"ASK_HUMAN","block_type":"login|captcha|paywall|consent|other","question":"What should the human do?","reasoning":"I'm blocked because..."}

**DONE**: The goal has been achieved. Output:
{"decision":"DONE","reasoning":"The goal is achieved because..."}

Rules:
- Always output exactly ONE decision
- For navigation: use full URLs with https://
- For clicking: use CSS selectors when possible, fall back to visible text
- If you see a login form and have no credentials → ASK_HUMAN
- If you see a captcha → ASK_HUMAN
- Do NOT attempt to brute-force logins or bypass captchas
```

### 4.5 _run_task 循环变更

`app/api/tasks.py` 中 `_run_task()` 的 STEP_COMPLETE 处理从:

```
# V2.0: 简单反应式
PolicyEngine.decide(goal, trajectory) → CONTINUE(action) / STOP
```

改为:

```
# V2.5: ReAct 认知式
STEP_COMPLETE → 提取 ObservationState(url/title/dom_summary)
  → ReActEngine.decide(goal, trajectory, observation)
    → ACT:       CONTINUE(action)
    → ASK_HUMAN: transition WAITING_USER, emit NEED_HUMAN, 暂停等待
    → DONE:      STOP(TASK_FINISHED)
```

### 4.6 ASK_HUMAN 触发场景

LLM 驱动的检测(非硬编码规则):

| 场景 | block_type | 示例 question |
|---|---|---|
| 登录页面 | login | "需要登录网站,请提供用户名和密码,或手动登录后告诉我继续" |
| 验证码 | captcha | "页面需要验证码验证,请手动完成验证后告诉我继续" |
| 支付确认 | paywall | "页面要求付费订阅,是否继续?" |
| Cookie 弹窗 | consent | "页面弹出 Cookie/隐私协议,请确认后告诉我继续" |
| 模糊导航 | other | "搜索结果有多个选项,请告诉我选哪一个" |

Fallback 规则(LLM 不可用时,在 ReActEngine._fallback_decide 中):

```python
_BLOCKER_PATTERNS: dict[str, str] = {
    r"captcha|verify.*human|prove.*you.*human": "captcha",
    r"sign.?in|log.?in|please.*authenticate": "login",
    r"subscribe|upgrade.*plan|payment.*required": "paywall",
    r"accept.*cookies|cookie.*consent|gdpr": "consent",
}
```

---

## 5. 用户中途插话(Human-in-the-loop)

### 5.1 两种场景

| 场景 | 发起方 | 协议流 |
|---|---|---|
| **Agent 求助** | Agent(ReActEngine) | ReActEngine → NEED_HUMAN → WAITING_USER → 用户 POST /tasks/{id}/messages → RESUME → ReActEngine 重新规划 |
| **用户主动中断** | User | 用户 POST /tasks/{id}/messages → INTERRUPT → Worker 暂停 → WAITING_USER → 用户输入 → RESUME → ReActEngine 重新规划 |

### 5.2 Worker INTERRUPT 处理

`worker/worker_session.py` 主循环新增:

```python
elif command.type == CommandType.INTERRUPT:
    self._interrupted = True
    self._worker_status = WorkerStatus.WAITING_CONFIRM
    emit_event(RuntimeEvent(event=EventType.INTERRUPTED, ...))
    # 回到主循环顶,等待 RESUME 或 STOP

elif command.type == CommandType.RESUME:
    self._interrupted = False
    self._worker_status = WorkerStatus.RUNNING
    emit_event(RuntimeEvent(event=EventType.RESUMED, ...))
    # Runtime 会在之后发 CONTINUE 带新动作

elif command.type == CommandType.PAUSE:
    self._should_pause_after_step = True
    # 完成当前步骤后暂停,不执行新步骤
```

`_execute_action()` 中增加中断检查:

```python
async def _execute_action(self, action, skill_name):
    # ... STEP_START 发射 ...
    result = await skill.execute(action)

    # V2.5: 检查是否被中断
    if self._interrupted:
        return  # 不发射 STEP_COMPLETE,Runtime 重新决策

    # ... 正常 STEP_COMPLETE 发射 ...
```

### 5.3 send_task_message 增强

`app/api/tasks.py` 的 `send_task_message()` 新增 RUNNING 状态处理:

```python
elif current_state == TaskState.RUNNING:
    # 用户中途插话 → INTERRUPT Worker
    cmd = Command(
        command_id=_new_cmd_id(),
        type=CommandType.INTERRUPT,
        payload={"reason": "user_interrupt", "user_message": payload.content},
    )
    await _task_state_mgr.transition(
        task_id, TaskState.WAITING_USER, f"用户中断: {payload.content[:80]}"
    )
    await runner.send_command(cmd)

elif current_state == TaskState.WAITING_USER:
    # 用户回复 Agent 求助(或继续中断)
    cmd = Command(
        command_id=_new_cmd_id(),
        type=CommandType.RESUME,
        payload={"feedback": payload.content},
    )
    await _task_state_mgr.transition(
        task_id, TaskState.RUNNING, f"用户回复: {payload.content[:80]}"
    )
    # ReActEngine 收到 RESUME 后重新 decide,然后发 CONTINUE
    await runner.send_command(cmd)
```

### 5.4 WAITING_USER 超时保护

在 `_run_task()` 中,进入 WAITING_USER 后启动 300s 定时器:

```python
if decision.decision_type == "ASK_HUMAN":
    await _task_state_mgr.transition(task_id, TaskState.WAITING_USER, ...)
    # 等待用户响应(超时 300s)
    try:
        event = await asyncio.wait_for(event_queue.get(), timeout=300.0)
    except TimeoutError:
        result_state = TaskState.FAILED
        result_reason = "用户 300s 未响应 Agent 求助"
        break
```

---

## 6. Agent 可观测增强

### 6.1 数据模型变更

#### task_steps 新增 7 列(全部 nullable)

| 列 | 类型 | 说明 |
|---|---|---|
| `duration_ms` | INTEGER | 步骤执行耗时(Worker 上报) |
| `llm_latency_ms` | INTEGER | LLM 调用延迟(Runtime 记录) |
| `tokens_prompt` | INTEGER | 输入 token 数 |
| `tokens_completion` | INTEGER | 输出 token 数 |
| `model_name` | VARCHAR(64) | 使用的模型(MiMo-V2.5 / deepseek-v4-pro 等) |
| `reasoning` | TEXT | ReAct 推理文本(think 步骤) |
| `step_type` | VARCHAR(16) DEFAULT 'act' | observe / think / act / human |

#### tasks 新增 3 列

| 列 | 类型 | 说明 |
|---|---|---|
| `total_tokens` | INTEGER DEFAULT 0 | 任务总 token(prompt+completion) |
| `total_cost_usd` | NUMERIC(10,6) DEFAULT 0 | 任务总成本 |
| `llm_model_used` | VARCHAR(64) | 任务使用的模型 |

### 6.2 迁移

单次 Alembic 迁移,原子事务:

```sql
-- task_steps: 7 列(全部 nullable,不阻塞现有写路径)
ALTER TABLE task_steps ADD COLUMN duration_ms INTEGER;
ALTER TABLE task_steps ADD COLUMN llm_latency_ms INTEGER;
ALTER TABLE task_steps ADD COLUMN tokens_prompt INTEGER;
ALTER TABLE task_steps ADD COLUMN tokens_completion INTEGER;
ALTER TABLE task_steps ADD COLUMN model_name VARCHAR(64);
ALTER TABLE task_steps ADD COLUMN reasoning TEXT;
ALTER TABLE task_steps ADD COLUMN step_type VARCHAR(16) DEFAULT 'act';

-- tasks: 3 列(有 DEFAULT,不阻塞现有写路径)
ALTER TABLE tasks ADD COLUMN total_tokens INTEGER DEFAULT 0;
ALTER TABLE tasks ADD COLUMN total_cost_usd NUMERIC(10,6) DEFAULT 0;
ALTER TABLE tasks ADD COLUMN llm_model_used VARCHAR(64);

-- 索引: 时间序列 + think 步骤查询
CREATE INDEX idx_task_steps_step_type ON task_steps(step_type)
    WHERE step_type IN ('think', 'human');
```

### 6.3 LLM 成本计算(纯函数)

```python
# service/cost.py

# 定价表: (input_price, output_price) per 1M tokens
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v4-pro": (0.55, 1.10),
    "mimo-v2": (0.10, 0.20),
    "mimo-v2.5": (0.10, 0.20),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}

def calculate_cost(model: str, tokens_prompt: int, tokens_completion: int) -> float:
    """计算 LLM 调用成本
    - 不匹配的 model → 返回 0.0(不抛异常,避免阻断任务)
    """
    input_price, output_price = _MODEL_PRICING.get(model, (0.0, 0.0))
    cost = (tokens_prompt / 1_000_000) * input_price + \
           (tokens_completion / 1_000_000) * output_price
    return round(cost, 6)
```

### 6.4 新增 API 端点

#### GET /agents/{id} — Agent 详情

```json
{
  "id": "uuid",
  "name": "Browser Agent",
  "description": "通用浏览器自动化 Agent",
  "health": "healthy",
  "lastTaskAt": "2026-06-11T10:30:00Z",
  "successRate24h": 0.95,
  "type": "browser",
  "status": "active",
  "config": {},
  "totalTasks": 42,
  "avgTokensPerTask": 1500,
  "avgDurationMs": 3200,
  "createdAt": "2026-06-10T08:00:00Z"
}
```

#### GET /agents/{id}/metrics?window=24h — 时间序列

```json
{
  "agent_id": "uuid",
  "window": "24h",
  "buckets": [
    {
      "ts": "2026-06-11T09:00:00Z",
      "tokens_total": 5000,
      "cost_usd": 0.002,
      "step_count": 10,
      "task_count": 2,
      "success_count": 2
    }
  ],
  "summary": {
    "successRate24h": 0.95,
    "totalTokens": 5000,
    "totalCostUsd": 0.002
  }
}
```

#### POST /agents/{id}/pause — 暂停 Agent

```
POST /agents/{id}/pause
→ 200 {"success": true, "agent_id": "...", "status": "paused"}
→ 409 {"success": false, "reason": "Agent already paused"}
```

行为: 正在运行的任务继续完成,新任务拒绝(409)。

#### POST /agents/{id}/resume — 恢复 Agent

```
POST /agents/{id}/resume
→ 200 {"success": true, "agent_id": "...", "status": "active"}
→ 409 {"success": false, "reason": "Agent already active"}
```

### 6.5 Redis 指标缓存

```python
# service/metrics_cache.py

class MetricsCache:
    """Agent 指标缓存 —— Redis 60s TTL

    每次 /agents 请求会触发 3 次 DB 聚合查询(agents + last_task_at + metrics)。
    对于 Dashboard 5s 轮询来说,60s 缓存减少 92% 的 DB 查询。
    """

    def __init__(self, redis: RedisClient) -> None: ...

    async def get_agent_metrics(self, agent_id: UUID) -> dict | None: ...
    async def set_agent_metrics(self, agent_id: UUID, data: dict, ttl: int = 60): ...
    async def invalidate(self, agent_id: UUID) -> None: ...  # 任务完成时调用
```

### 6.6 Dashboard Stats SQL 重构

当前 `stats.py` 用 Python 过滤(list_by_user + for 循环),数据量大时无法接受。改为:

```sql
SELECT
  COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') AS tasks_today,
  COUNT(*) FILTER (WHERE status = 'running') AS running,
  COALESCE(SUM(total_tokens) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours'), 0) AS tokens_today,
  COALESCE(SUM(total_cost_usd) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours'), 0) AS cost_today,
  COUNT(*) FILTER (WHERE status IN ('completed','failed','cancelled')
    AND updated_at >= NOW() - INTERVAL '24 hours') AS terminal_24h,
  COUNT(*) FILTER (WHERE status = 'completed'
    AND updated_at >= NOW() - INTERVAL '24 hours') AS success_24h
FROM tasks
WHERE user_id = :user_id;
```

一次性返回所有仪表盘卡片数据,无需 Python 过滤。

---

## 7. Agent 启停控制

### 7.1 状态机

```
active ──pause──→ paused ──resume──→ active
  │                 │
  └──deprecated     └──(running tasks complete, new tasks rejected)
```

### 7.2 Task 创建时的 Agent 状态校验

`app/api/tasks.py` 的 `create_task()` 中,在 `_resolve_default_agent_id()` 之后增加:

```python
# 校验 agent 是否 active(V2.5 agent 生命周期)
if _pg_client is not None and agent_id is not None:
    session = _pg_client.session()
    try:
        from app.repository.agent import AgentRepository
        agent = await AgentRepository(session).get_by_id(agent_id)
        if agent is None or agent.status != "active":
            status_text = agent.status if agent else "not_found"
            raise HTTPException(409, f"Agent is {status_text}, cannot accept new tasks")
    finally:
        await session.close()
```

### 7.3 前端影响

- Agent 列表: active 的 agent 出现在任务创建下拉中,paused 的不出现
- 新建任务: 选 paused agent 返回 409,前端展示错误提示

---

## 8. 前端契约

### 8.1 字段兼容性

所有新字段为 Optional,渐进式消费。现有字段名/类型/枚举值不变:

| 现有字段 | V2.5 变更 | 兼容 |
|---|---|---|
| Agent 全部字段(id/name/description/health/lastTaskAt/successRate24h) | 不变 | ✅ |
| Task 列表项字段(goal/status/createdAt 等) | agentName 已有(来自V2), costUsd 从硬编码0→真实值 | ✅ |
| Task 详情 fields | +costUsd(真实值), +modelUsed | ✅ |
| TaskStep | +stepType, +reasoning, +llmLatencyMs, +modelUsed | ✅ 可选字段 |
| WebSocket RuntimeEvent | +新 event 类型 | ✅ 前端忽略未知类型 |

### 8.2 前端需适配的变更

1. **ChatInput**: RUNNING 状态改为可输入(发送指令/中断),WAITING_USER 时显示"回复 Agent"提示
2. **HumanResponseDialog**: 新组件 — NEED_HUMAN 事件时弹出,展示 Agent 问题+截图+输入框+发送按钮
3. **Timeline**: think 步骤显示推理内容(可折叠),展示 token 消耗和 LLM 延迟
4. **Agent 详情页/面板**: 展示详细指标(type/status/totalTasks/avgTokens/avgDuration)
5. **Agent 卡片**: 增加 pause/resume 操作按钮(仅 Dashboard 可见)

---

## 9. 实施阶段(4 PR)

| PR | 内容 | 风险 | 预计文件 |
|---|---|---|---|
| **PR1: 协议+数据层** | Protocol 枚举/payload + alembic 迁移 + model/schema 列新增 + 状态转换更新 | 低(纯数据) | 10 |
| **PR2: ReAct 引擎+API** | ReActEngine + _run_task 改造 + TimelineRecorder think 订阅 + agent detail/metrics/pause/resume 端点 + stats SQL 重构 | 中(决策逻辑) | 10 |
| **PR3: Worker 中断+人机协作** | Worker INTERRUPT/PAUSE/RESUME 处理 + send_task_message 增强 + WAITING_USER 超时 + NEED_HUMAN 事件流 | 中(Worker 协议) | 6 |
| **PR4: 前端适配+测试** | ChatInput 行为 + HumanResponseDialog + Timeline think 渲染 + Agent 详情 + 全部单元/集成测试 | 中(UI) | 14 |

每个 PR 后运行: `pytest + mypy + ruff`

---

## 10. 测试策略

### 单元测试(Python)

| 文件 | 覆盖 |
|---|---|
| `tests/runtime/test_react_engine.py` | Observe→Think→Decide, ASK_HUMAN/DONE/ACT, LLM 失败 fallback |
| `tests/runtime/test_transitions_v25.py` | WAITING_USER 转换,非法转换拒绝 |
| `tests/service/test_agent_v25.py` | detail 构造, metrics 计算, pause/resume 校验 |
| `tests/service/test_cost_calculator.py` | 所有模型成本,零 token 边界,未知模型→0.0 |
| `tests/service/test_metrics_cache.py` | Redis 命中/未命中/失效 |
| `tests/api/test_agent_v25.py` | GET /agents/{id}, GET metrics, POST pause/resume, 幂等 |
| `tests/api/test_task_messages_v25.py` | INTERRUPT from RUNNING, RESUME from WAITING_USER, 终态拒绝 |
| `tests/protocol/test_v25_schemas.py` | 全部新 payload 序列化/反序列化 |
| `tests/repository/test_task_metrics.py` | 时间序列聚合,百分位查询,成本聚合 |

### 集成测试

| 文件 | 覆盖 |
|---|---|
| `tests/integration/test_interrupt_flow.py` | 完整 INTERRUPT → WAITING_USER → RESUME 流程(mock Worker) |
| `tests/integration/test_react_cycle.py` | Observe→Think→Act 完整循环(mock LLM) |
| `tests/integration/test_agent_lifecycle.py` | Pause→create rejected→Resume→create accepted |

### 前端测试(Vitest)

| 覆盖 |
|---|
| ChatInput disabled/enabled per task status |
| HumanResponseDialog 渲染(login/captcha/paywall/other) |
| Timeline think 步骤渲染(推理折叠/展开) |

---

## 11. 关键技术点

### 11.1 ReActEngine 与 PolicyEngine 的 fallback 关系

```
ReActEngine.decide()
  │
  ├── LLM 成功 → 返回 DecisionResponse(decision_type=ACT|ASK_HUMAN|DONE)
  │
  └── LLM 失败(timeout/网络错误/JSON 解析失败)
        │
        ├── PolicyEngine.decide() → 返回 ACT(导航/点击)
        │     │
        │     └── PolicyEngine 也失败 → _fallback_decide(regex URL/网站映射/Bing 搜索)
        │
        └── 最终兜底: navigate to Bing search
```

### 11.2 ASK_HUMAN 检测精度

- **不做硬编码规则**(除了 LLM fallback 时的 regex)
- LLM 通过 system prompt 中的"INSTRUCTIONS"部分自主判断
- 测试时 mock LLM 返回 `{"decision":"ASK_HUMAN",...}`,验证状态转换正确
- 生产环境观察 1 周,统计 ASK_HUMAN 准确率,必要时调整 prompt

### 11.3 Worker INTERRUPT 安全性

- Playwright 操作(click/input_text/navigate)本身是亚秒级的,中断窗口极小
- `page.goto()` 默认 30s 超时,加 `page.wait_for_timeout()` 轮询 `self._interrupted` flag
- INTERRUPT 后 Worker 不发射 STEP_COMPLETE,Runtime 通过 WAITING_USER 超时兜底

### 11.4 WAITING_USER 的双重触发路径

```
路径 A(Agent 求助):
  STEP_COMPLETE → ReActEngine → ASK_HUMAN → WAITING_USER

路径 B(用户中断):
  send_task_message → INTERRUPT → WAITING_USER
```

两条路径最终都进入 WAITING_USER,用户通过 POST /tasks/{id}/messages 发送回复后统一走 RESUME → ReActEngine 重新规划 → CONTINUE。

### 11.5 N+1 防御(Agent 指标查询)

`GET /agents` 已有 3 次 SQL(via asyncio.gather)。`GET /agents/{id}/metrics` 只有 1 次 SQL(时间序列聚合),无需额外优化。Redis 缓存(MetricsCache)覆盖高频轮询场景(/agents + /stats/dashboard)。

### 11.6 前端渐进式消费

所有新字段为 Optional,前端不升级也能正常使用。旧版前端:
- 忽略 THINK_START/THINK_COMPLETE/NEED_HUMAN 等新事件(只处理已知类型)
- stepType 字段缺失 → 默认渲染为 tool 步骤
- costUsd 从 0 → 真实值(数值类型不变)

---

## 12. 潜在风险与防御

### 12.1 LLM ASK_HUMAN 误判(不该问的时候问了)

**风险**: ReAct system prompt 太激进,正常页面也被判定为阻塞。
**防御**:
- Prompt 中明确 "Only ASK_HUMAN when there is a CLEAR blocker"
- YOLO 模式下可以跳过 ASK_HUMAN(全部当 ACT 处理)
- PR2 上线后观察 ASK_HUMAN 频率,迭代 prompt

### 12.2 Worker INTERRUPT 不实际停止 Playwright

**风险**: `page.goto(url)` 正在执行中,INTERRUPT flag 设置在 Python 层但 Playwright 在 Chromium 进程内忙碌。
**防御**:
- Playwright 操作均有超时(默认 30s),不会永久阻塞
- 在 `_execute_action()` 中 `skill.execute()` 返回后立即检查 `_interrupted` flag
- 最坏情况: 当前步骤完成后才中断(延迟 < 30s)

### 12.3 WAITING_USER 永久挂起

**风险**: 用户忘记回复 Agent,任务一直 WAITING_USER。
**防御**:
- 300s 超时 → FAILED("user_unresponsive")
- 前端 HumanResponseDialog 显示倒计时
- 超时后保存 checkpoint(可 resume)

### 12.4 ReAct LLM 延迟拖慢任务

**风险**: 每次 STEP_COMPLETE 后多一次 LLM 调用(Think 阶段),任务延长。
**防御**:
- ReActEngine 设 30s 超时,超时 fallback 到 PolicyEngine
- Think 步骤的 token 和延迟写入 task_steps,可观测
- 后续 V3 可加入"跳过 Think"(仅观察→行动)的快速路径

### 12.5 前端契约破坏

**风险**: 新字段/新事件导致旧前端报错。
**防御**:
- 所有新字段 Optional(default 值)
- WebSocket 事件处理中 try/except 未知事件类型
- 字段名严格保持 camelCase(与现有前端对齐)

---

## 13. 修订记录

- 2026-06-11 v1: 初稿 — ReAct 引擎 + 中途插话 + 可观测增强 + 启停控制
