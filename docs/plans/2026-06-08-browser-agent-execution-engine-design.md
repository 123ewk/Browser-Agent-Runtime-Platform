# Browser Agent 执行引擎设计方案

> 日期: 2026-06-08
> 状态: 设计冻结，可进入编码阶段
> 对应 Phase: Phase 1 — Browser Agent 执行引擎

---

## 一、设计哲学 (Design Philosophy)

### 核心原则

1. **用成熟框架，不自己造轮子** — Browser Use 负责浏览器感知+执行，Playwright 负责浏览器控制
2. **自己只做 Runtime + 编排层** — Agent Runtime、Skill System、Checkpoint、Observability、Human-in-the-loop
3. **控制权不丢失** — Worker 有局部自主能力，但 Runtime 始终掌握全局控制

### 三层 Agent 架构

```
🧠 L1: Planner (战略层)
  职责: 用户目标 → 子目标列表
  特点: 不碰 DOM，不执行浏览器，只做任务分解
  拥有: 全局视角

⚙️ L2: Worker (战术层 / Goal-Oriented Agent)
  职责: 单个子目标 → 完成/失败/需确认
  特点: 短循环自主能力，多步推理，不脱离目标边界
  拥有: Browser Use + Playwright

🧩 L3: Browser Use + Playwright (执行层)
  职责: click / type / navigate / extract
  特点: 无目标意识，纯能力系统
```

---

## 二、整体架构

```
┌────────────────────────────────────────────────────────────┐
│  Frontend (Next.js 15 + React 19)                          │
│  Agent Workspace | Timeline | BrowserPreview | ChatInput   │
│  AuthGuard | AuthModal                                     │
└────────────────────────┬───────────────────────────────────┘
                         │ WebSocket
                         ▼
┌────────────────────────────────────────────────────────────┐
│  FastAPI Runtime (单进程)                                   │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  TaskStateManager        (状态机 — 唯一真相源)         │  │
│  │  EventBus                (内存事件总线)                 │  │
│  │  Planner                 (LLM 全局规划)                │  │
│  │  BrowserTaskRunner       (Worker 子进程管理)           │  │
│  │  ProcessWatchdog         (超时检测)                    │  │
│  │  HumanGate               (人工确认拦截)                │  │
│  │  CheckpointManager       (Recovery Point 管理)         │  │
│  │  WebSocketManager        (事件 → 前端)                 │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────┬───────────────────────────────────┘
                         │ stdin (JSON Lines)
                         │ stdout (JSON Lines)
                         ▼
┌────────────────────────────────────────────────────────────┐
│  Browser Worker (子进程)                                    │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  WorkerSession          (主控制器)                    │  │
│  │  BrowserManager         (Playwright BrowserContext)   │  │
│  │  StateExtractor          (页面感知)                    │  │
│  │  GoalChecker             (目标完成判定)                │  │
│  │  ActionPlanner           (LLM 局部决策)               │  │
│  │  ActionRiskEvaluator     (动作风险等级)                │  │
│  │  ScreenshotManager       (截图管理)                    │  │
│  │  InterruptHandler        (STOP/CONTINUE/REJECT)       │  │
│  │  CheckpointHook          (子目标完成保存)              │  │
│  │  StdoutEmitter           (事件 → stdout)              │  │
│  │  StdinListener           (stdin → 命令)               │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Browser Use (感知 + 执行能力提供)                     │  │
│  │  Playwright + Chromium                                │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

---

## 三、协议定义 (Protocol First)

### 目录结构

```
backend/app/runtime/
├── __init__.py
├── protocol/
│   ├── __init__.py
│   ├── types.py           # 枚举定义
│   ├── schemas.py         # 事件/命令模型
│   ├── constants.py       # 协议版本、超时常量
│   └── transitions.py     # 状态转换规则
├── event_bus.py
├── task_state.py
├── task_runner.py
├── checkpoint.py
├── human_gate.py
├── watchdog.py
└── ws_manager.py
```

### types.py — 枚举定义

```python
from __future__ import annotations
from enum import Enum


class EventType(str, Enum):
    """Worker → Runtime 事件类型"""
    WORKER_READY = "WORKER_READY"
    WORKER_HEARTBEAT = "WORKER_HEARTBEAT"
    STEP_START = "STEP_START"
    STEP_COMPLETE = "STEP_COMPLETE"
    SCREENSHOT = "SCREENSHOT"
    PROGRESS = "PROGRESS"
    NEED_CONFIRM = "NEED_CONFIRM"
    ERROR = "ERROR"
    TASK_FINISHED = "TASK_FINISHED"
    COMMAND_ACK = "COMMAND_ACK"


class CommandType(str, Enum):
    """Runtime → Worker 命令类型"""
    START = "START"
    CONTINUE = "CONTINUE"
    REJECT = "REJECT"
    STOP = "STOP"
    # V2: INTERRUPT, NEW_GOAL, PAUSE, RESUME


class TaskState(str, Enum):
    """Runtime 任务状态机"""
    PENDING = "pending"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunMode(str, Enum):
    YOLO = "yolo"
    SEMI = "semi"


class TaskResult(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkerStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"


class ConfirmSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FailureType(str, Enum):
    SYSTEM_ERROR = "SYSTEM_ERROR"
    BROWSER_ERROR = "BROWSER_ERROR"
    TIMEOUT = "TIMEOUT"
    USER_CANCELLED = "USER_CANCELLED"
    MAX_STEPS_EXCEEDED = "MAX_STEPS_EXCEEDED"
    GOAL_FAILED = "GOAL_FAILED"
```

### schemas.py — 事件/命令模型

```python
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field

from .types import (
    EventType, CommandType, TaskResult,
    WorkerStatus, ConfirmSeverity, RiskLevel, FailureType,
)

PROTOCOL_VERSION = "1.0"


# ==================== 核心消息 ====================

class RuntimeEvent(BaseModel):
    """Worker → Runtime | EventBus 内流通的统一事件"""
    version: str = PROTOCOL_VERSION
    event_id: str
    event: EventType
    ts: datetime
    task_id: str
    payload: dict = Field(default_factory=dict)


class Command(BaseModel):
    """Runtime → Worker 统一命令"""
    command_id: str
    type: CommandType
    payload: dict = Field(default_factory=dict)


# ==================== 事件 Payload ====================

class StepCompletePayload(BaseModel):
    index: int
    action: str          # "navigate" | "click" | "input_text" | ...
    summary: str
    url: str | None = None


class ScreenshotPayload(BaseModel):
    s3_key: str


class ProgressPayload(BaseModel):
    current: int
    total: int


class NeedConfirmPayload(BaseModel):
    action_tag: str      # "publish_video" | "delete_resource" | "submit_form"
    question: str        # 显示给用户看的中文问题
    severity: ConfirmSeverity = ConfirmSeverity.MEDIUM


class ErrorPayload(BaseModel):
    error_type: str      # FailureType 值或自定义
    message: str
    retryable: bool = False


class TaskFinishedPayload(BaseModel):
    status: TaskResult
    summary: str


class HeartbeatPayload(BaseModel):
    seq: int
    status: WorkerStatus = WorkerStatus.RUNNING


# ==================== 命令 Payload ====================

class StartPayload(BaseModel):
    session_id: str
    goal: str
    storage_state_path: str | None = None
    run_mode: RunMode = RunMode.SEMI
    max_steps: int = 20
    timeout_seconds: int = 120


class ContinuePayload(BaseModel):
    approved: bool
    feedback: str = ""


class RejectPayload(BaseModel):
    reason: str
```

### transitions.py — 状态转换规则

```python
_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.PENDING:           {TaskState.RUNNING},
    TaskState.RUNNING:           {TaskState.WAITING_CONFIRM, TaskState.PAUSED,
                                   TaskState.STOPPING,       TaskState.FAILED,
                                   TaskState.COMPLETED},
    TaskState.WAITING_CONFIRM:   {TaskState.RUNNING,         TaskState.STOPPING,
                                   TaskState.FAILED},
    TaskState.PAUSED:            {TaskState.RUNNING,         TaskState.STOPPING,
                                   TaskState.FAILED},
    TaskState.STOPPING:          {TaskState.CANCELLED},
    # COMPLETED, FAILED, CANCELLED 是终态，不能转出
}


def can_transition(current: TaskState, new: TaskState) -> bool:
    """校验状态转换合法性"""
    allowed = _TRANSITIONS.get(current, set())
    return new in allowed
```

---

## 四、Runtime 核心组件

### 4.1 TaskStateManager

```
职责: Runtime 任务状态机，唯一真相源
模式: Producer（发布状态变更事件），非 Consumer
```

```python
class TaskStateManager:
    """状态变更 → 发布 TASK_STATE_CHANGED 到 EventBus"""

    async def transition(self, task_id: str, to_state: TaskState, reason: str = "") -> TaskState:
        # 1. 校验合法性（can_transition）
        # 2. 更新 DB
        # 3. 发布 RuntimeEvent(TASK_STATE_CHANGED) 到 EventBus
        # 4. 返回新状态

    async def get_state(self, task_id: str) -> TaskState: ...
```

### 4.2 EventBus

```
职责: 内存事件总线，异步广播
模式: Producer → EventBus → Consumer (async gather, return_exceptions=True)
```

```python
class EventBus:
    """V1: 内存事件总线，不需要 Redis Pub/Sub"""

    async def publish(self, event: RuntimeEvent) -> None:
        """async gather 所有 handler，return_exceptions=True 防止单个 handler 失败影响其他"""

    def subscribe(self, event_type: EventType | str, handler: Callable[[RuntimeEvent], Awaitable[None]]) -> None: ...

    def unsubscribe(self, event_type: EventType | str, handler: Callable) -> None: ...
```

**Consumer 清单:**

| Consumer | 订阅事件 | 职责 |
|---|---|---|
| WebSocketManager | 所有用户可见事件 | 转发给前端 |
| CheckpointManager | STEP_COMPLETE, TASK_STATE_CHANGED | 按触发器保存 Recovery Point |
| ProcessWatchdog | WORKER_HEARTBEAT, STEP_START, STEP_COMPLETE | 超时检测 |
| HumanGate | NEED_CONFIRM | 暂停 Worker，等待用户 |
| TimelineRecorder | STEP_START, STEP_COMPLETE, ERROR, SCREENSHOT, TASK_STATE_CHANGED | 写入 DB task_steps |

### 4.3 BrowserTaskRunner

```
职责: Worker 子进程生命周期管理 + stdin/stdout 协议
```

```python
class BrowserTaskRunner:
    """管理一个 Worker 子进程"""

    # 后台协程:
    #   _stdin_writer_loop()    — Command Queue → JSON Lines → process.stdin
    #   _stdout_reader_loop()   — process.stdout → JSON Lines → RuntimeEvent → EventBus
    #   _stderr_collector_loop()— process.stderr → 日志文件 + 异常检测
    #   _process_monitor_loop() — 监听 proc.wait()，检测异常退出

    async def start_task(self, context: TaskContext) -> None:
        """
        1. 启动子进程 (asyncio.create_subprocess_exec)
        2. 启动 4 个后台协程
        3. 等待 WORKER_READY (asyncio.Event, timeout=10s)
        4. 发 START 命令
        """

    async def send_command(self, cmd: Command) -> None:
        """往 Command Queue 放命令"""

    async def stop_task(self, timeout: float = 5.0) -> None:
        """三阶段停止: STOP → wait → kill"""

    async def cleanup(self) -> None:
        """清理: 发哨兵 → 取消协程 → 关进程"""
```

### 4.4 ProcessWatchdog

```
职责: 监控 Worker 心跳，超时触发 WATCHDOG_TIMEOUT 事件
耦合: 不持有 Runner 引用，只发布事件
```

### 4.5 HumanGate

```
职责: 拦截 NEED_CONFIRM → 推 WebSocket → 等待用户确认 → 发 CONTINUE/REJECT
```

### 4.6 CheckpointManager

```
职责: Recovery Point 管理（简化版）
保存内容: Task State + Current URL + Storage State Path + Last Successful Step
触发条件: 关键步骤完成 / 子目标完成 / 人工确认前 / 任务结束
V1 不做: 完整 Graph State / Agent State / Memory
```

---

## 五、Worker 内部架构

### 5.1 模块结构

```
backend/worker/
├── __init__.py
├── main.py                         # CLI entry: argparse → WorkerSession
├── worker_context.py               # WorkerContext
├── execution_contract.py           # ExecutionContract (执行边界)
├── worker_session.py               # WorkerSession (主控制器)
├── browser_manager.py              # BrowserManager (Playwright + BrowserContext)
├── browser_use_adapter.py          # BrowserUseAdapter (封装 Browser Use 为能力层)
├── action_planner.py               # ActionPlanner (LLM 决策下一步动作)
├── action_executor.py              # ActionExecutor (执行原子操作，调用 Adapter)
├── state_extractor.py              # StateExtractor (页面状态提取)
├── goal_checker.py                 # GoalChecker (双通道: Rule-based + LLM)
├── risk_evaluator.py               # ActionRiskEvaluator (动作风险)
├── screenshot_manager.py           # ScreenshotManager (截图时机)
├── interrupt_queue.py              # InterruptQueue (事件驱动中断系统)
├── stdout_emitter.py               # StdoutEmitter (JSON Lines → stdout)
├── stdin_listener.py               # StdinListener (stdin → Command)
└── checkpoint_hook.py              # CheckpointHook (状态保存)
```

### 5.2 WorkerSession 主循环

```python
class WorkerSession:
    """
    执行层三层模型:
      ActionPlanner  (决策)     → 输出 Action
      ActionExecutor (执行)     → 调用 Adapter 执行 Action
      BrowserUseAdapter (能力)  → 封装 Browser Use 的感知+执行原语
    """

    async def _execute_goal(self, goal: str):
        """Goal-Oriented Execution Loop"""
        contract = ExecutionContract(goal=goal, max_steps=20, timeout_seconds=120)
        step_count = 0

        while not self._interrupt.is_stop_requested():
            # 边界检查
            if step_count >= contract.max_steps:
                self._emit(ERROR, {"error_type": "MAX_STEPS_EXCEEDED"})
                break

            # 感知
            state = await self._state_extractor.extract()

            # 目标完成校验（双通道: rule-based 优先, LLM fallback）
            if await self._goal_checker.is_complete(state, contract):
                self._emit(TASK_FINISHED, {"status": "completed"})
                return

            # 失败检测
            if await self._goal_checker.has_failed(state, contract):
                break

            # 决策: Planner 决定下一步动作
            action = await self._action_planner.decide(state, contract)

            # 风险评估
            risk = self._risk_evaluator.evaluate(action)
            if risk.is_high:
                await self._request_human_confirm(action)
                if self._interrupt.was_rejected():
                    continue

            # 截图（按触发器）
            if self._screenshot_manager.should_capture(action, risk):
                ...

            # 执行: Executor 调用 Adapter 层
            self._emit(STEP_START, {"action": action.type})
            result = await self._action_executor.execute(action)
            self._emit(STEP_COMPLETE, {"summary": result.summary})

            step_count += 1
```

### 5.3 Goal-Oriented Worker vs 完全自主 Agent 的区别

| 维度 | 完全自主 Agent (C) | Goal-Oriented Worker (本方案) |
|---|---|---|
| 目标范围 | 整个用户任务 | 单个子目标 |
| 控制权 | Runtime 无法介入 | Runtime 全程可控 |
| Human-in-the-loop | 不支持 | 原生支持 (RiskEvaluator + NEED_CONFIRM) |
| 可观测性 | 黑盒 | 每步事件 + 截图 |
| Checkpoint | 粒度粗 | 子目标级 Recovery Point |
| 失败恢复 | 全局重试 | 子目标级重试 |

---

## 六、Browser Use Adapter / Execution Layer

### 6.1 三层职责

```
ActionPlanner                  → 输出: Action
(LLM 根据页面状态 + 目标，决定"下一步做什么")

ActionExecutor                 → 调用: Adapter
(执行 Action，处理重试/重规划/失败，不关心底层)

BrowserUseAdapter              → 调用: Browser Use + Playwright
(封装 Browser Use 为可插拔能力层，可被替换)
```

### 6.2 Action —— 统一动作表示

```python
@dataclass
class Action:
    type: str                    # "navigate" | "click" | "input_text" | ...
    target: ElementSelector | None  # 目标元素 (可选)
    value: str | None               # 输入值 (可选)
    description: str                # 人类可读描述，给 Timeline 用
    reasoning: str                  # LLM 决策理由，用于 trace/debug
    confidence: float               # 0.0-1.0，用于 risk evaluator / retry policy
```

### 6.3 BrowserUseAdapter 接口

```python
class BrowserUseAdapter:
    """封装 Browser Use 为可插拔执行后端"""

    async def extract_state(self) -> PageState:
        """DOM 提取 → 页面摘要"""

    async def execute_action(self, action: Action) -> ActionResult:
        """执行原子操作"""

    async def wait_for_state_change(
        self, previous_state: PageState, timeout: int = 5
    ) -> PageState:
        """等待页面状态稳定后返回新状态。
        解决 Web Automation 核心坑: 执行 ≠ 状态立即更新"""

    async def get_interactive_elements(self) -> list[ElementInfo]:
        """可交互元素列表（给 LLM 决策用）"""

    async def screenshot(self) -> bytes:
        """当前页面截图"""
```

### 6.4 ActionExecutor —— 三层失败模式

```python
class ActionExecutor:
    """
    执行可靠性层。
    三种失败模式，不同处理策略:
    """

    async def execute(self, action: Action) -> ActionResult:
        for attempt in range(self._max_retries):
            try:
                result = await self._adapter.execute_action(action)
                # 执行后等待状态稳定
                new_state = await self._adapter.wait_for_state_change(...)
                return result
            except RetryableError:
                continue       # 网络抖动/超时 → 重试
            except StateMismatchError:
                return REPLAN  # DOM 已变 → 需要重新观察+决策
            except FatalError:
                raise          # 浏览器崩溃 → 直接失败
```

**三种失败类型的处理策略:**

| 错误类型 | 含义 | 处理 |
|---|---|---|
| `RetryableError` | 网络抖动、超时、临时失败 | 重试（最多 N 次） |
| `StateMismatchError` | 页面状态与预期不符，DOM 已变化 | 触发 replan：重新 extract_state + decide |
| `FatalError` | 浏览器崩溃、Chromium 退出 | 直接向 Runtime 报告 FATAL_ERROR |

### 6.5 Adapter 可替换性

```
ActionExecutor
    ↓ (统一接口)
BrowserUseAdapter            ← V1 实现
PlaywrightDirectAdapter      ← V2 可选
SeleniumAdapter              ← V2 可选
RPAToolAdapter               ← V2 可选
```

---

## 七、Failure Recovery & Replanning System

### 7.1 分层恢复系统

```
三个决策层，各负责自己的"局部不确定性":

Runtime (Goal-level):
  子目标失败 → 重新规划 / 切换策略 / 报告用户

WorkerSession (Step-level):
  StateMismatch → re-extract + re-decide（不出 Worker 边界）

ActionExecutor (Action-level):
  RetryableError → 重试
  Timeout → 重试 → StateMismatch → 触发上层 replan
```

### 7.2 RecoveryContext —— 防死循环机制

```python
@dataclass
class RecoveryContext:
    """跟踪当前子目标内已失败的尝试，避免重复无效操作"""
    failed_actions: list[Action] = field(default_factory=list)
    failed_selectors: list[str] = field(default_factory=list)
    visited_urls: list[str] = field(default_factory=list)
    replan_count: int = 0
    max_replans: int = 3
```

WorkerSession 每次 replan 前检查: 同一个 selector 失败 ≥ 2 次 → 不再重试，直接上报 Runtime。

### 7.3 Recovery Decision Function

```python
def decide_recovery(error: Error, ctx: RecoveryContext) -> RecoveryAction:
    """规则引擎: 根据错误类型 + 上下文决定恢复行为"""

    if error.is_retryable and ctx.retry_count < 2:
        return RETRY

    if ctx.replan_count >= ctx.max_replans:
        return REPORT_FAILURE  # 超出 replan 上限，交 Runtime

    if error.is_state_mismatch:
        return REPLAN          # 重新 observe + decide

    if error.is_fatal:
        return ABORT           # Worker 级别终止
```

### 7.4 GoalChecker 三类失败

| 类型 | 含义 | V1 处理 |
|---|---|---|
| HARD_FAILURE | 页面结构不支持，元素不存在 | 直接上报 Runtime |
| SOFT_FAILURE | 可绕路（如找不到"发布"按钮但能找到"上传"） | 内部 replan |
| TIME_FAILURE | 超时（子目标超过 timeout_seconds） | 上报 Runtime，由 Planner 决定重试还是放弃 |

### 7.5 Recovery 策略矩阵

| 失败类型 | 检测方式 | V1 处理策略 |
|---|---|---|
| Action 超时 | Executor timeout | 重试 2 次 → StateMismatch → 重新决策 |
| Action 失败（元素未找到） | Browser Use 返回错误 | 重试 2 次 → NEED_CONFIRM |
| Goal 无法完成 | GoalChecker 超时/超步数 | 报告 ERROR 给 Runtime → Planner |
| Worker 崩溃（进程退出） | Watchdog 120s 无心跳 | 重启 Worker → 从上一个 Recovery Point 继续 |
| LLM 调用失败 | ActionPlanner 抛异常 | 重试 3 次 → 报告 FATAL_ERROR |

---

## 八、stdin/stdout 协议

### 协议概览

```
[Runtime] ←── stdout (JSON Lines) ── [Worker]
[Runtime] ──→ stdin  (JSON Lines) ──→ [Worker]
[Runtime]      stderr (收集到文件，不参与协议)
```

### Worker → Runtime 事件

| 事件 | 时机 | 关键 Payload |
|---|---|---|
| WORKER_READY | 启动完成，等 START | 无 |
| WORKER_HEARTBEAT | 每 30 秒 | seq, status |
| STEP_START | 动作开始前 | action, description |
| STEP_COMPLETE | 动作完成后 | summary, url |
| SCREENSHOT | 按触发器 | s3_key |
| PROGRESS | 进度变化 | current, total |
| NEED_CONFIRM | 高风险操作 | action_tag, question, severity |
| ERROR | 错误发生 | error_type, message, retryable |
| TASK_FINISHED | 任务结束 | status (completed/failed/cancelled), summary |
| COMMAND_ACK | 收到命令 | command_id |

### Runtime → Worker 命令

| 命令 | 时机 | Payload |
|---|---|---|
| START | 任务开始 | session_id, goal, storage_state_path, run_mode |
| CONTINUE | 人工确认通过 | approved, feedback |
| REJECT | 人工拒绝 | reason |
| STOP | 停止任务 | 无 |

### 完整消息序列（单个子目标）

```
Worker                                      Runtime
  │                                            │
  │── WORKER_READY ───────────────────────→    │
  │←── START {goal, session_id, ...} ──────    │
  │                                            │
  │  [开始 Browser Use 局部自主循环]            │
  │── HEARTBEAT {seq:1} ─────────────────→     │
  │── STEP_START {navigate} ──────────────→    │
  │── STEP_COMPLETE ──────────────────────→    │
  │── HEARTBEAT {seq:2} ─────────────────→     │
  │── SCREENSHOT ────────────────────────→     │
  │── STEP_START {click} ────────────────→     │
  │── STEP_COMPLETE ──────────────────────→    │
  │                                            │
  │  [发现高风险操作]                           │
  │── NEED_CONFIRM ──────────────────────→    │  HumanGate 拦截
  │                                            │  推 WebSocket 给前端
  │                                            │  等待用户确认
  │←── CONTINUE {approved:true} ───────────    │
  │                                            │
  │── STEP_START {click_publish} ─────────→    │
  │── TASK_FINISHED {completed} ──────────→    │  子目标完成
```

---

## 九、Task State Machine

```
PENDING ──→ RUNNING ──→ WAITING_CONFIRM ──→ RUNNING ──→ COMPLETED
               │              │                           ↑
               │              └──→ RUNNING (通过 approve)  │
               ├──→ FAILED (附带 failure_type)             │
               ├──→ STOPPING ──→ CANCELLED                 │
               └──→ PAUSED ──→ RUNNING                     │
                                                           │
              (终态: COMPLETED, FAILED, CANCELLED 不能转出)  │
```

---

## 十、v1 范围（Phase 1）

### v1 要做的

| 模块 | 说明 |
|---|---|
| Runtime: TaskStateManager | 状态机 + 状态变更事件 |
| Runtime: EventBus | 内存事件总线，async gather 广播 |
| Runtime: BrowserTaskRunner | 子进程生命周期 + stdin/stdout |
| Runtime: ProcessWatchdog | 120s 无心跳 → WATCHDOG_TIMEOUT |
| Runtime: HumanGate | NEED_CONFIRM 拦截 + 推送 + 等待 |
| Runtime: CheckpointManager | Recovery Point (简化版) |
| Runtime: WebSocketManager | EventBus → 前端推送 |
| Runtime: Planner | LLM 单步规划（选择一个 Skill） |
| Worker: WorkerSession | Goal-Oriented 执行循环 |
| Worker: BrowserManager | Playwright + BrowserContext |
| Worker: BrowserUseAdapter | 封装 Browser Use 为可插拔能力层 |
| Worker: ActionPlanner | LLM 决策下一步动作，输出 Action |
| Worker: ActionExecutor | 执行 Action，处理重试/失败/超时 |
| Worker: ActionRiskEvaluator | 动作风险等级判定 |
| Worker: ScreenshotManager | 按触发器截图 |
| Worker: InterruptHandler | STOP/CONTINUE/REJECT |
| Worker: StateExtractor + GoalChecker | 页面感知 + 目标判定 |
| Worker: StdinListener + StdoutEmitter | IPC 通信 |
| Browser 能力 | navigate / click / input_text / upload / extract_text / wait / screenshot |

### v1 明确不做

| 模块 | 原因 |
|---|---|
| 实时浏览器镜像 (Live Browser Stream) | 太重，截图+Timeline 足够 |
| User Interrupt（中途改目标） | v1 只做 STOP，INTERRUPT/NEW_GOAL v2 |
| Selector 修复 / 视觉导航 | Browser Use 已有基础 selector，失败就人工接管 |
| 多浏览器协同 | 复杂度 x10 |
| 远程 Browser 容器 (Docker) | Docker 化以后再说 |
| 验证码识别 | 专项对抗，不是平台该解决的问题 |
| 复杂工作流编排 (Multi-Step Plan) | v1 Planner 只选一个 Skill |
| Skill Marketplace | v1 只有 Browser Skill |
| Cost 统计明细 | v1 只记总 token 数 |

---

## 十一、关键设计决策记录

| # | 决策 | 选择 | 被否决方案 | 理由 |
|---|---|---|---|---|
| 1 | Browser Use 角色 | 执行能力层 (非 Agent) | Browser Use Agent 全权执行 | 保持 Runtime 控制权 |
| 2 | Worker 执行模式 | Goal-Oriented (局部自主) | Runtime 逐步决策 / 完全自主 | 平衡控制力与效率 |
| 3 | Worker 集成方式 | 子进程 (JSON Lines IPC) | 同进程直接 import | 隔离性，崩溃不波及 Runtime |
| 4 | Event Bus | 内存 asyncio | Redis Pub/Sub, Kafka | V1 单进程，不需要跨进程 |
| 5 | 状态管理 | TaskStateManager 为唯一真相源 | 各模块自维护状态 | 避免状态不一致 |
| 6 | Checkpoint | Recovery Point (简化) | 完整 Graph State | V1 没有复杂工作流 |
| 7 | 截图策略 | 按触发器保存 | 每步截图 | 性能考虑，避免 300 张截图 |
| 8 | Storage State | 按需保存（关键节点） | 每步保存 | Playwright 性能考虑 |
| 9 | 停止策略 | 三阶段: STOP→wait→kill | 直接 kill | 优雅停止，避免数据丢失 |
| 10 | Human-in-the-loop | ActionRiskEvaluator 判定 | 每步确认 / 不做 | 平衡安全性与流畅性 |
| 11 | 执行层模型 (3层) | ActionPlanner → ActionExecutor → BrowserUseAdapter | ActionPlanner 直接执行 | 方便替换 Browser Use / Playwright 或加 RPA 引擎 |
| 12 | GoalChecker | 双通道: Rule-based 优先, LLM fallback | 纯 LLM 判断 | 避免无限循环, 提高效率 |
| 13 | 中断系统 | 事件驱动 (asyncio.Queue) | 阻塞式 wait_for | 可扩展 STOP/PAUSE/RESUME/RETRY |

---

## 十二、技术栈

| 层次 | 技术 |
|---|---|
| Runtime (Python) | FastAPI, Pydantic, structlog, SQLAlchemy async |
| Worker (Python) | Browser Use, Playwright, Pydantic |
| IPC | JSON Lines (stdin/stdout) |
| 数据库 | PostgreSQL (task/checkpoint/session), Redis (cache) |
| 文件存储 | MinIO/S3 (screenshots, storage_state) |
| 前端 | Next.js 15, React 19, TanStack Query, Zustand, Tailwind CSS |
| 实时通信 | WebSocket (Runtime → 前端) |

---

## 十三、工程落地路径 (Engineering Implementation Path)

### 核心理念: 先跑通，再优化

设计已经完成。现在最重要的是**一周内跑通端到端 MVP**，而不是完美实现所有组件。

### MVP 最小可运行版本 (第一周)

目标是: **Runtime 启动 Worker → Worker 打开百度首页 → 截图 → 事件回到 Runtime → 推前端**

```
Day 1-2: 协议 + 骨架
  ├── backend/app/runtime/protocol/types.py
  ├── backend/app/runtime/protocol/schemas.py
  ├── backend/app/runtime/protocol/transitions.py
  ├── backend/app/runtime/event_bus.py
  ├── backend/app/runtime/task_state.py
  └── 单元测试验证序列化/反序列化

Day 3-4: Worker 能跑
  ├── backend/worker/main.py (CLI entry, 打印 WORKER_READY)
  ├── backend/worker/stdout_emitter.py (JSON Lines → stdout)
  ├── backend/worker/stdin_listener.py (stdin → Command → 打印)
  ├── backend/worker/worker_session.py (接收 START, 打印 goal, TASK_FINISHED)
  ├── backend/app/runtime/task_runner.py (创建子进程, 读写 stdin/stdout)
  └── 手动测试: python -m worker.main 能收发 JSON Lines

Day 5-6: 浏览器能打开
  ├── Worker: browser_manager.py (Playwright launch + Context)
  ├── Worker: browser_use_adapter.py (execute_action: goto)
  ├── Worker: screenshot_manager.py (截图 → 本地文件)
  ├── Worker: action_executor.py (execute + 返回结果)
  └── 手动测试: Worker START → 打开百度 → 截图 → TASK_FINISHED

Day 7: 全链路
  ├── Runtime: ws_manager.py (EventBus → WebSocket)
  ├── Runtime: task_runner.py 完整版 (多协程)
  ├── 前端: Agent Workspace 对接 (Timeline 显示事件)
  └── 最终测试: 前端提交 → Runtime → Worker → 百度 → 截图 → 前端显示
```

**第一周结束时的可演示能力:**
前端点击"执行" → 输入"打开百度" → Runtime 创建任务 → Worker 启动 → Playwright 打开百度首页 → 截图 → 事件流回前端 → Timeline 显示 → 任务完成

### 后续迭代

```
第 2 周: Browser Use 接入 + ActionPlanner 局部决策
  ├── ActionPlanner (LLM decide: click? input? navigate?)
  ├── GoalChecker (Rule-based: 页面标题是否包含目标关键词)
  ├── 能执行: "打开百度, 搜索'Python'" (Navigate → Input → Click)
  └── 把截图存到 MinIO 而不是本地

第 3 周: 控制层
  ├── ActionRiskEvaluator (敏感操作拦截)
  ├── HumanGate (NEED_CONFIRM → 前端弹窗 → 确认/拒绝)
  ├── ProcessWatchdog (120s 无心跳 → 重启)
  └── 支持: 高风险操作弹人工确认

第 4 周: 可靠性
  ├── CheckpointManager (Recovery Point)
  ├── RecoveryContext (防死循环)
  ├── Worker ActionExecutor 三层失败处理
  └── 能演示: Worker 崩溃后自动恢复

第 5-6 周: 完成
  ├── Planner (LLM 子目标拆解, v1 只调 Browser Skill)
  ├── Skill System (BaseSkill + Registry + capabilities)
  ├── 前端完整对接 (Timeline + BrowserPreview + Status)
  └── Docker Compose 全栈一键部署
```

### 目录结构初始化

```
backend/
├── app/runtime/                     # 新增
│   ├── __init__.py
│   ├── protocol/
│   │   ├── __init__.py / types.py / schemas.py / constants.py / transitions.py
│   ├── event_bus.py / task_state.py / task_runner.py
│   ├── task_runner_registry.py / checkpoint.py
│   ├── human_gate.py / watchdog.py / ws_manager.py
│   └── skill/
│       ├── __init__.py / base.py / registry.py / browser_skill.py
├── worker/                          # 新增: 独立子进程包
│   ├── __init__.py / main.py / worker_context.py
│   ├── execution_contract.py / worker_session.py
│   ├── browser_manager.py / browser_use_adapter.py
│   ├── action_planner.py / action_executor.py
│   ├── state_extractor.py / goal_checker.py
│   ├── risk_evaluator.py / screenshot_manager.py
│   ├── interrupt_queue.py / checkpoint_hook.py
│   ├── stdout_emitter.py / stdin_listener.py
```

### 前端 Timeline MVP 对接

前端已有 `AgentStreamEvent` 类型和 `subscribeTaskStream()`，只需:
1. 扩展事件类型解析，支持 RuntimeEvent 全字段
2. Timeline 组件消费 STEP_START / STEP_COMPLETE / ERROR / SCREENSHOT
3. BrowserPreview 组件消费 SCREENSHOT 事件
4. ChatInput 创建任务而非发送消息

### 技术依赖清单 (新增)

```toml
# backend/pyproject.toml 新增依赖
browser-use>=0.1.0   # Browser Use 浏览器感知+执行
```

前端无新增依赖，现有 TanStack Query + WebSocket 已够用。
