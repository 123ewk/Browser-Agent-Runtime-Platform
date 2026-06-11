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
5. NEED_CONFIRM 事件已定义但 Worker 从未发射,WAITING_CONFIRM 状态闲置 — **V2.5 决定: 同步补上 NEED_CONFIRM 实现**(理由见 §1,V2.5 目标 3 "人机协作" 只做 NEED_HUMAN 覆盖不完整)

### V2.5 目标

| # | 目标 | 验收标准 |
|---|---|---|
| 1 | ReAct 决策引擎 | PolicyEngine → ReActEngine (基于 langchain 抽象),输出 Observe→Think→Act 循环,Timeline 可见推理过程 |
| 2 | 用户中途插话 | RUNNING 状态可发送消息,Agent 暂停并重新规划 |
| 3 | 人机协作(Agent 求助 + 风险确认) | 遇到登录/验证码等阻塞 → NEED_HUMAN → WAITING_USER; 遇到高风险操作 → NEED_CONFIRM → WAITING_CONFIRM; 两者都实现 Worker 端真实发射 |
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
> 📌 **2026-06-11 修订**: 决定 V2.5 同步实现 NEED_CONFIRM(详见 §0 问题 5),实际覆盖率维持 70%(NEED_CONFIRM 是 V2.0 已有事件,补全实现而非新增能力)。

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
├── api/stats.py               # 改: Python 过滤→SQL 聚合(P2-12 参数化)
├── service/agent.py           # 改: +详细指标计算 + Redis 缓存集成
├── service/cost.py            # 新增: LLM 成本计算(读 YAML 定价表,P1-8)
├── service/metrics_cache.py   # 新增: Redis 60s TTL 指标缓存
├── runtime/react_engine.py    # 新增: ReAct 决策引擎(基于 langchain,非自造) # 📌 2026-06-11 修订
├── runtime/react_bridge.py    # 新增: V25ReActExecutor 自定义 AgentExecutor(P1-5)
├── runtime/react_tools.py     # 新增: LangChain @tool 定义(navigate/click/.../ask_human)
├── runtime/react_callbacks.py # 新增: RuntimeBridgeCallback 桥接 LangChain 事件→V2.5 事件
├── runtime/policy_engine.py   # 保留: 作为 LLM 失败时的 fallback
├── runtime/timeline_recorder.py # 改: +think/observe/human 步骤订阅 + 累加 total_cost_usd(P2-13 原子累加)
├── runtime/protocol/types.py  # 改: +EventType/CommandType/TaskState/WorkerStatus(W2.5 增 WAITING_USER,P0-1)
├── runtime/protocol/schemas.py # 改: +新 payload 类型 + StepCompletePayload 补 dom_summary/visible_text/aborted
├── runtime/protocol/transitions.py # 改: +WAITING_USER 转换
├── runtime/protocol/constants.py # 改: PROTOCOL_VERSION → "2.0.0" + 兼容策略(见 §3)
├── repository/task.py         # 改: +时间序列聚合 + 延迟百分位 + 成本聚合
├── repository/task_step.py    # 改: +token 聚合 + 步骤耗时百分位
├── model/task.py              # 改: +total_tokens/total_cost_usd/llm_model_used
├── model/task_step.py         # 改: +9 个新列(含 dom_summary/visible_text)
├── model/checkpoint.py        # 改: +pending_ask_human JSONB 字段
├── model/agent.py             # 改: agents.status 枚举(新增 DRAINED,见 §7)
├── core/config/llm_pricing.yaml # 新增: LLM 定价表(P1-8 外置)
├── core/lifespan.py           # 改: init_react_engine 替代 init_policy_engine
├── worker/worker_session.py   # 改: +INTERRUPT/PAUSE/RESUME 命令分发 + StepComplete 上报 dom_summary
└── worker/skill/browser_skill.py # 改: 导航后提取 dom_summary / visible_text
└── worker/skill/risk_heuristics.py # 新增: NEED_CONFIRM 触发白名单(P2-9)
```

---

## 3. 协议层变更(Protocol V2.5)

### 3.0 版本兼容策略

**核心问题**:V2.0 [constants.py](backend/app/runtime/protocol/constants.py) 中 `PROTOCOL_VERSION = "1.0"`,Worker 启动时 Runtime 校验兼容性,**主版本不同 → 拒绝连接**。V2.5 升级到 `2.5` 等于主版本号变化,会导致:
- 滚动升级期间 V2.5 Runtime 与 V1 Worker 通信失败
- 现有运行中的 V1 Worker 进程全部断开
- 长期运行的任务(30min+)中途崩溃

**V2.5 决策**:

1. **PROTOCOL_VERSION = "2.0.0"**(📌 P2-11 修订,采用 SemVer 三段式)
2. **强制同时升级**:
   - 部署 V2.5 Runtime 时**必须同步升级所有 Worker 镜像**(单一镜像,统一升级)
   - 不支持 V1 Worker 进程与 V2.5 Runtime 混合运行
   - 部署顺序:Rolling restart 时先停所有 V1 Worker 进程 → 升级 Runtime → 启动新 Worker(blue-green 模式)
3. **Worker 端版本协商保留**:`app/runtime/protocol/constants.py` 加 `SUPPORTED_PROTOCOL_VERSIONS: list[str] = ["1.0.0", "2.0.0"]`,Runtime 启动时同时接受两个版本(过渡期),但 V1 Worker 收到 V2.5 协议新事件时会忽略(向后兼容读)
4. **新事件类型全部 Optional**:Worker 收到未知 EventType 时**忽略不报错**,不阻塞主循环
5. **脱机策略**:`docs/upgrade-protocol-v2.5.md` 记录升级 checklist(部署前查 Runtime 进程是否完全重启 + Worker 镜像版本号)

**版本号语义规范**(P2-11 修订):

| 位置 | 含义 | 兼容性规则 |
|---|---|---|
| **MAJOR**(第 1 段) | 协议结构破坏性变更 | 跨 MAJOR 必须强制同时升级(本 V1.0 → V2.0) |
| **MINOR**(第 2 段) | 新增事件类型 / payload 字段(向后兼容) | Runtime 升级后,旧 Worker 收到新事件类型→忽略(读) |
| **PATCH**(第 3 段) | bugfix / 文档修正(完全兼容) | 不需要任何升级动作 |

**为什么 V2.5 用 "2.0.0" 而不是 "2.5"**(P2-11 解释):
- SemVer 规范: "2.5" 应理解为 "MAJOR=2, MINOR=5",后续 2.6/2.7 应是兼容的 MINOR 升级(只加事件不破坏结构)
- 但 V2.5 实际改动包含 `INTERRUPT/PAUSE/RESUME` 三个新命令 + `WAITING_USER` 新状态 + `aborted` 字段,**是破坏性变更**,应升级 MAJOR
- 用 "2.0.0" 明确表达"破坏性变更"语义,后续 V2.x.y 才是兼容的 MINOR 升级
- 配套的 `SUPPORTED_PROTOCOL_VERSIONS` 比较逻辑只需判断 MAJOR(1 vs 2)是否一致,MINOR/PATCH 不参与兼容性判断

**版本号示例**(未来演进路径):

| 版本 | 含义 | 升级要求 |
|---|---|---|
| 1.0.0 | V1 协议(PolicyEngine,无 INTERRUPT) | - |
| 2.0.0 | V2.5 协议(ReAct, INTERRUPT/PAUSE/RESUME, WAITING_USER) | 强制 Runtime + Worker 同时升级 |
| 2.1.0 | V2.6 新增 STEP_ABORTED 事件(可选消费) | Runtime 升级,Worker 可不升(忽略未知事件) |
| 3.0.0 | V3 重构协议(如改 JSON-RPC 替代现在的 stdio JSON) | 强制同时升级 |

> 📌 **2026-06-11 修订**(P2-11):原 §3.0 用 `PROTOCOL_VERSION = "2.5"` 不符合 SemVer 规范。改为 `"2.0.0"` 三段式,清晰表达"破坏性变更"语义,后续 V2.1.x/V2.2.x 才是兼容升级。

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
    NEED_CONFIRM = "NEED_CONFIRM"         # V1 定义, V2.5 真正实现 Worker 端发射(见 §3.1 P2-9)
    ERROR = "ERROR"
    TASK_FINISHED = "TASK_FINISHED"
    TASK_STATE_CHANGED = "TASK_STATE_CHANGED"
    COMMAND_ACK = "COMMAND_ACK"
    WATCHDOG_TIMEOUT = "WATCHDOG_TIMEOUT"

    # --- V2.5 新增 ---
    THINK_START = "THINK_START"           # ReAct 思考阶段开始 (Runtime 合成)
    THINK_COMPLETE = "THINK_COMPLETE"     # ReAct 思考完成(含 reasoning 文本) (Runtime 合成)
    OBSERVE_COMPLETE = "OBSERVE_COMPLETE" # 页面观察完成 (Runtime 合成,见 §4.5)
    NEED_HUMAN = "NEED_HUMAN"             # Agent 能力边界(login/captcha/paywall) (Worker 发射)
    HUMAN_RESPONSE = "HUMAN_RESPONSE"     # 用户已回复 Agent (前端通过 send_task_message 端点进入 Runtime)
    INTERRUPTED = "INTERRUPTED"           # Worker 已被中断 (Worker 发射,见 §5.2)
    RESUMED = "RESUMED"                   # Worker 已从中断恢复 (Worker 发射,见 §5.2)
```

> 📌 **2026-06-11 修订**(P3-15):原 §3.1 EventType 中 NEED_CONFIRM 出现两次(V1 保留 + V2.5 新增 注释里又说"V2.0 已定义,V2.5 真正实现 Worker 端发射"),Python 同一枚举类不能有两个同名成员(虽然文档用代码块注释表达,但容易误以为要写两行)。**只在 V1 保留区保留一行**,把"V2.5 真正实现" 的注释合并到同一行,避免歧义。

**事件源约定**(V2.5 明确,避免时间轴错乱):

| 事件 | 发射方 | 时机 |
|---|---|---|
| STEP_START | Worker | 浏览器动作开始 |
| STEP_COMPLETE | Worker | 浏览器动作完成,含 `dom_summary` / `visible_text` |
| OBSERVE_COMPLETE | **Runtime 合成** | Runtime 收到 STEP_COMPLETE 后提取 ObservationState,合成事件后发给 EventBus(给 TimelineRecorder 等订阅者) |
| THINK_START / THINK_COMPLETE | **Runtime 合成** | ReActEngine.decide() 入口和出口 |
| NEED_HUMAN | Worker | Worker 端 BrowserSkill 检测到阻塞(登录/验证码等) |
| NEED_CONFIRM | **Worker 端简单启发式(见 P2-9 决策)** | V2.5 不引入 ActionRiskEvaluator,用 action_type 白名单触发 |
| HUMAN_RESPONSE | Runtime | Runtime 收到 send_task_message 端点调用 |
| INTERRUPTED / RESUMED | Worker | 收到 INTERRUPT/RESUME 命令后立即发射 |

> 📌 **2026-06-11 修订**:原设计未明确 OBSERVE_COMPLETE 是 Worker 端还是 Runtime 端,实现时容易两边都发或都不发。明确"Runtime 合成"后,Worker 端只发 STEP_COMPLETE(含完整 DOM 数据),Runtime 拆分合成 OBSERVE_COMPLETE 给可观测消费方,保证事件源单一。

**NEED_HUMAN vs NEED_CONFIRM 区别**:
- `NEED_CONFIRM`: 系统已经知道下一步,但需要用户批准(高风险操作:"是否发布?")
- `NEED_HUMAN`: 系统无法继续,需要人类提供能力(登录凭据/验证码/人工判断)

**V2.5 NEED_CONFIRM 触发方式**(P2-9 决策):

| 方案 | 是否采用 | 理由 |
|---|---|---|
| A. ReActEngine LLM 推理 | ❌ 否 | LLM 对"风险"判断不稳定,容易"啥都问"或"啥都不问";判定逻辑应与决策分离 |
| B. **action_type 白名单 + URL pattern**(采用) | ✅ 是 | V2.5 范围: 简单、可测试、无 ML 依赖;Worker 端 `BrowserSkill.execute()` 在执行前检查 |
| C. ActionRiskEvaluator(完整 ML 推理) | ❌ 否 | V3 范围,见 §0 "不在 V2.5 范围" |

**V2.5 NEED_CONFIRM 触发白名单**(`worker/skill/risk_heuristics.py` 新增):

```python
# worker/skill/risk_heuristics.py

# action_type 级白名单
_RISKY_ACTION_TYPES: set[str] = {
    "publish",       # 发布文章/评论
    "delete",        # 删除数据
    "submit_payment",# 支付提交
    "send_email",    # 发送邮件(可能误发)
    "update_profile",# 修改个人信息
}

# URL 关键词白名单(粗粒度,容易误报,作为补充)
_RISKY_URL_PATTERNS: list[str] = [
    r"/submit", r"/confirm", r"/pay", r"/checkout", r"/delete", r"/publish",
]

def needs_confirm(action: ActionDetail, current_url: str) -> tuple[bool, str]:
    """判断是否需要 NEED_CONFIRM

    Returns: (True, reason) 或 (False, "")
    """
    if action.type in _RISKY_ACTION_TYPES:
        return True, f"action_type={action.type} 是高风险操作"
    for pattern in _RISKY_URL_PATTERNS:
        if re.search(pattern, current_url, re.IGNORECASE):
            return True, f"URL 匹配风险模式: {pattern}"
    return False, ""
```

**触发时序**(`BrowserSkill.execute()` 内部):
1. Worker 收到 `CONTINUE(action=...)` 命令
2. `BrowserSkill.execute()` 调用 `risk_heuristics.needs_confirm(action, current_url)`
3. **若需要确认**: 不执行 action,先发 `NEED_CONFIRM` 事件(含 action 详情 + reason),Runtime 转 `WAITING_CONFIRM`
4. **若不需要**: 正常执行,发 `STEP_START` → `STEP_COMPLETE`

> 📌 **2026-06-11 修订**(P2-9):原 §3.1 说"Worker 端 ActionRiskEvaluator 评估" 触发 NEED_CONFIRM,但 §0 又明确"ActionRiskEvaluator 不在 V2.5 范围" 矛盾。V2.5 决策: 用 action_type 白名单 + URL pattern 简单启发式触发,V3 再上 ML 推理的 ActionRiskEvaluator。

### 3.2 CommandType(激活 V2 预留)

```python
class CommandType(StrEnum):
    # V1
    START = "START"
    CONTINUE = "CONTINUE"
    REJECT = "REJECT"
    STOP = "STOP"

    # V2.5 激活
    INTERRUPT = "INTERRUPT"   # Runtime→Worker: 中断当前动作,发 STEP_COMPLETE(aborted=true)后转 WAITING_USER
    PAUSE = "PAUSE"           # Runtime→Worker: 完成当前 STEP_COMPLETE 后转 PAUSED(Worker 不退出,只挂起主循环)
    RESUME = "RESUME"         # Runtime→Worker: 从 PAUSED/WAITING_USER 恢复,统一 payload 协议(见下)
```

**INTERRUPT vs PAUSE 语义对比**(V2.5 明确,避免混用):

| 维度 | INTERRUPT | PAUSE |
|---|---|---|
| 触发方 | 用户中途发消息 / Agent 求助 | 用户主动暂停 / 维护 |
| 终态 | WAITING_USER | PAUSED |
| 当前 step 行为 | **完成并标记 aborted=true**(Runtime 重新规划) | **完成**(发 STEP_COMPLETE 后停止) |
| Worker 进程 | 继续运行,等 RESUME | 继续运行,等 RESUME |
| 适用场景 | "改变方向""Agent 求助" | "用户暂时离开""需要思考" |
| 后续命令 | RESUME(带新 feedback) | RESUME(无 payload) |

**RESUME 命令统一 payload 协议**(P2-10 修订,消除歧义):

`CommandType.RESUME` 是单一枚举值,但触发场景有 2 种(PAUSE 后 / INTERRUPT 后)。V2.5 决策:**统一 payload 协议**,Worker 不需要区分来源,只需把 payload 透传给 Runtime。

```python
# RESUME payload 统一 schema
class ResumePayload(BaseModel):
    """RESUME 命令的 payload —— 无论来自 PAUSE 还是 INTERRUPT,Worker 都按此解析"""
    feedback: str = ""                 # 用户反馈(空=纯恢复,非空=用户补充指令)
    ask_human_block_type: str = ""     # 透传:Agent 求助时的 block_type(INTERRUPT 路径才用)
    ask_human_question: str = ""       # 透传:Agent 求助时的 question(供 ReActEngine resume 时用)
    previous_interrupt_reason: str = ""# 透传:上一次 INTERRUPT 的 reason(user_interrupt / agent_ask_human)
```

| 触发场景 | payload.feedback | payload.ask_human_* | Worker 行为 |
|---|---|---|---|
| **PAUSE → RESUME** | `""` | `""` | 清空暂停标志,继续主循环,等 Runtime 发 CONTINUE 带新 action |
| **INTERRUPT(user) → RESUME** | 用户消息原文 | `""` | 清空中断标志,继续主循环,Runtime 会发 CONTINUE(action 基于新 feedback 重新规划) |
| **INTERRUPT(agent ask_human) → RESUME** | 用户回复 | 上次 ask_human 的 block_type/question | 同上,但 Runtime 用 ask_human_* 构造"用户已解决 X 阻塞" 的 trajectory 上下文 |

**为什么 Worker 不区分 PAUSE 来源和 INTERRUPT 来源**:
- Worker 的职责只是"恢复主循环 + 接收新命令",不需要知道"为什么被中断"
- 来源信息(feedback / ask_human_*) 由 Runtime 写进 payload,Worker 透传即可
- 实现简单:Worker 代码只有一份 RESUME 处理逻辑,不引入 `if reason == "pause"` 分支

> 📌 **2026-06-11 修订**(P2-10):原 §3.2 说"PAUSE 的 RESUME 无 payload,INTERRUPT 的 RESUME 带 feedback",但 `CommandType.RESUME` 是单枚举,Worker 收到时无法区分。统一为带 ResumePayload 后,Worker 实现简单,Runtime 端构造 payload 时根据来源填充不同字段即可。

> 📌 **2026-06-11 修订**:原 V2.5 设计 INTERRUPT 与 PAUSE 在 §5.2 行为描述矛盾(一个说"立即中断",一个说"完成当前步骤后"),且代码片段注释说"不发射 STEP_COMPLETE"又与"立即中断"语义冲突。明确为"INTERRUPT 放弃当前 step,PAUSE 完成当前 step"后,代码层面只有一套状态:Worker 收到 INTERRUPT 时设 `_interrupt_requested = True` + 不发 STEP_COMPLETE,收到 PAUSE 时设 `_pause_after_step = True` + 发 STEP_COMPLETE。

### 3.3 TaskState(任务级状态机) + AgentStatus(Agent 级状态机,V2.5 明确分离)

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

class AgentStatus(StrEnum):
    """Agent 整体状态(V2.5 新增,与 TaskState 命名空间分离)

    与 TaskState.PAUSED 的区别:
    - TaskState.PAUSED = 单个任务的暂停(用户操作)
    - AgentStatus.DRAINED = Agent 整体停止接收新任务(运维操作)
    """
    ACTIVE = "active"          # 正常运行
    DRAINED = "drained"        # V2.5 新增: 停止接收新任务(原 V2.5 设计叫 'paused',与 TaskState 冲突改名)
    DEPRECATED = "deprecated"  # 永久下线
```

**为什么改名 `paused` → `DRAINED`**:

V2.0 引入 `agents.status` 字段时用 `'active' | 'paused' | 'deprecated'`,V2.5 启停控制继续用 `paused`。但**前端的"暂停"按钮有两套含义**:
- 任务详情页"暂停" → 操作 `TaskState.PAUSED`(单个任务挂起)
- Agent 卡片"暂停" → 操作 `AgentStatus.paused`(整体停止)

同一个英文 `paused` 指两个不同实体 → 前端命名空间混乱、API 字段名冲突、用户口头沟通歧义。

V2.5 决策:Agent 状态改用 Kubernetes 业界术语 `DRAINED`(排水),既与 `TaskState.PAUSED` 区分,又比 `INACTIVE` / `OFFLINE` 更精确表达"正在运行的任务继续完成,新任务拒绝"。

> 📌 **2026-06-11 修订**:原 V2.5 设计 Agent 状态用 `paused`,与 `TaskState.PAUSED` 命名冲突,改用 `DRAINED` 避免歧义。

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

# OBSERVE_COMPLETE 事件 payload (Runtime 合成,源数据来自 STEP_COMPLETE)
class ObserveCompletePayload(BaseModel):
    step_index: int
    url: str | None = None
    title: str | None = None
    dom_summary: str = ""       # 压缩后的 DOM 文本(Worker 上报,Runtime 转发)
    visible_text: str = ""      # 页面可见文本(前 2000 字符,Worker 上报,Runtime 转发)

# INTERRUPT 命令 payload
class InterruptPayload(BaseModel):
    reason: str                 # "user_interrupt" | "agent_ask_human" | "system"
    user_message: str = ""      # 用户说的内容(用户主动中断时填,Agent 求助时为空)
    ask_human_block_type: str = ""  # Agent 求助时的 block_type(login/captcha 等)
    ask_human_question: str = ""    # Agent 求助时的 question(供 resume 后回传 ReActEngine)

# StepCompletePayload 扩展字段
class StepCompletePayload(BaseModel):
    # ... V1 字段 ...
    duration_ms: int | None = None      # 📌 V2.0 已定义但 V2 Worker 未发; V2.5 真正填充(Worker 上报)
    dom_summary: str = ""               # 📌 V2.5 新增: Worker 在导航类动作后提取
    visible_text: str = ""              # 📌 V2.5 新增: Worker 在导航类动作后提取
    step_type: str = "act"              # 📌 V2.5: observe|think|act|human
    reasoning: str = ""                 # 📌 V2.5: think 步骤的推理文本

# DecisionResponse 扩展字段
class DecisionResponse(BaseModel):
    # ... V1 字段(skill, action, reasoning, is_terminal) ...
    decision_type: str = "ACT"          # 📌 V2.5: ACT|ASK_HUMAN|DONE
    confidence: float = 1.0             # 📌 V2.5
    tokens_used: int = 0                # 📌 V2.5
    model_used: str = ""                # 📌 V2.5
    llm_latency_ms: int = 0             # 📌 V2.5
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

**数据流职责划分**(V2.5 明确):

| 数据 | 产生方 | 消费方 | 协议事件 |
|---|---|---|---|
| `url` / `title` | Worker (BrowserSkill) | Runtime (ObservationState) | STEP_COMPLETE |
| `dom_summary` | **Worker (BrowserSkill 调 `page.evaluate(js)` 提取结构化 DOM 摘要,截断到 3000 字符)** | Runtime (合成 OBSERVE_COMPLETE) | STEP_COMPLETE.payload.dom_summary |
| `visible_text` | **Worker (BrowserSkill 调 `page.inner_text('body')` 截断到 2000 字符)** | Runtime | STEP_COMPLETE.payload.visible_text |
| `recent_errors` | **Runtime 维护滑窗**(每 task 独立,见 §4.3.1) | Runtime (ObservationState) | 本地状态,不发事件 |

**`dom_summary` vs `visible_text` 的区别**(V2.5 明确,P1-6 修订):

| 字段 | 含义 | 提取方式 | 大小 | 用途 |
|---|---|---|---|---|
| `visible_text` | 页面**真实可见**的纯文本(去标签、去脚本) | `page.inner_text('body')` | 2000 字符 | ReAct LLM 推理主体输入 |
| `dom_summary` | 页面**结构化摘要**(含可交互元素:按钮/输入框/链接 + 关键属性) | `page.evaluate(js_extract)` (见下) | 3000 字符 | 复杂场景补充(元素定位/aria 标签) |

**`dom_summary` 提取 JS**(P1-6 修订:不用 `page.content()`,而用结构化提取):

```javascript
// 在 page.evaluate() 中执行 —— 提取可交互元素 + 关键文本
() => {
    const elements = Array.from(document.querySelectorAll(
        'button, input, a, [role="button"], [role="link"], h1, h2, h3, [aria-label]'
    ));
    const summary = elements.slice(0, 100).map(el => {
        const tag = el.tagName.toLowerCase();
        const text = (el.innerText || el.value || el.ariaLabel || '').slice(0, 100);
        const attrs = [];
        if (el.id) attrs.push(`id=${el.id}`);
        if (el.name) attrs.push(`name=${el.name}`);
        if (el.type) attrs.push(`type=${el.type}`);
        if (el.href) attrs.push(`href=${el.href.slice(0, 50)}`);
        return `<${tag}${attrs.length ? ' ' + attrs.join(' ') : ''}>${text}</${tag}>`;
    }).join('\n');
    return summary.slice(0, 3000);  // 截断到 3000 字符
}
```

**为什么不直接用 `page.content()`**(P1-6 否决):
- `page.content()` 返回完整 HTML,含 `<script>`、`<style>`、SVG 路径、注释
- 3000 字符大概率截到 `<style>` 或 SVG 路径,关键内容(<button>Click here</button>)被截掉
- 实测:在 GitHub 首页 `page.content()` 前 3000 字符中,可读文本仅占 30%(其余是 CSS/SVG)
- 改用 `page.evaluate(js_extract)` 后,可读内容占比 > 85%,LLM 推理质量明显更好

**`visible_text` 用 `inner_text('body')` 不变**:visible_text 是"用户能看到的文字",已经隐式排除了 script/style,无需修改。

**为什么 Worker 端提取,不是 Runtime 端**:
- Runtime 与 Worker 是两个独立进程(Runtime 起 BrowserTaskRunner,Worker 是子进程)
- Runtime 没有 BrowserManager 实例,无法直接调 `page.content()`
- 现有 BrowserSkill.execute() 已经返回 `result.url` / `result.title`,扩展 `result.dom_summary` / `result.visible_text` 是最小改动
- 性能:Worker 提取后只传字符串(3000 字符上限),Runtime 不用 IPC 反向查询

> 📌 **2026-06-11 修订**(P1-6):原 §4.3 说用 `page.content()` 截断 3000 字符,但 `page.content()` 含大量 CSS/SVG/脚本,截断质量差。改为 `page.evaluate(js_extract)` 结构化提取可交互元素后,信息密度提升 ~3x,LLM 推理质量更好。

### 4.3.1 `recent_errors` 滑窗实现(P1-7 明确)

**存储位置**: Runtime 进程内存 `_run_task` context 中,每 task 独立 deque,**不持久化**。

```python
# api/tasks.py 中的 _run_task() 协程局部变量
from collections import deque

# 在 _run_task() 函数体内初始化
self._recent_errors: deque[str] = deque(maxlen=3)    # 📌 V2.5 明确: 进程内 deque,跟 task 生命周期

# EventBus 订阅 ERROR 事件(本协程内)
event_bus.subscribe(EventType.ERROR, self._on_error_event)

def _on_error_event(self, event: RuntimeEvent) -> None:
    """维护最近 3 个 ERROR 事件的滑窗"""
    self._recent_errors.append(event.payload.get("message", ""))

# 在下一次 ReActEngine.decide() 调用前
observation = ObservationState(
    url=...,
    title=...,
    dom_summary=...,
    visible_text=...,
    recent_errors=list(self._recent_errors),    # 喂给 LLM
)
```

**关键设计点**:
- **进程内 deque,不进 Redis**: Redis 会有序列化/反序列化开销,滑窗只是"喂给 LLM"的一次性数据,重启丢失可接受
- **每 task 独立**: `_run_task()` 协程内创建,任务结束销毁。多 task 并发时滑窗互不干扰
- **滑窗大小=3**: 实测 LLM 推理只需"最近错误",超过 3 个反而干扰
- **不持久化**: Runtime 重启后丢失是可接受的(error 已经写入 task_steps 表,TimelineRecorder 已订阅),滑窗只是给当前正在推理的 LLM 提供"最近失败上下文"

> 📌 **2026-06-11 修订**(P1-7):原 §4.3 只说"Runtime 维护滑窗" 一句,缺失存储位置 / 隔离 / 持久化策略。明确为"每 task 独立 deque,进程内,不持久化" 后,实现简单且符合"滑窗=LLM 临时输入" 的本质。

### 4.4 ReAct System Prompt(英文 prompt, P3-16 决策说明)

**为什么 prompt 用英文而不是中文**(P3-16 解释,看似违反 AGENTS.md "注释用中文"):
- AGENTS.md §2"所有注释必须使用中文"针对的是**项目源代码注释**(docstring / inline comment),**不**针对 prompt 文本
- prompt 是给 LLM 看的,**不是**给开发者看的:
  1. 英文 prompt 训练数据更多,主流模型对英文指令的遵循度普遍高于中文
  2. 浏览器场景的术语(CSS selector / click / input 等)在英文 LLM 训练集中占比远高于中文
  3. JSON 输出 schema 在英文 prompt 中格式更稳定(LangChain tool calling schema 本身是英文)
- 因此:**项目代码注释中文(prompt 模板常量变量名 / 函数 docstring),prompt 文本内容用英文**

> 📌 **2026-06-11 修订**(P3-16):原 §4.4 给出英文 prompt 但未说明原因,容易让 reviewer 觉得"违反中文注释约束"。明确"prompt ≠ 注释" 后,约束边界清晰:代码注释中文、prompt 文本英文(LLM 训练效率)。

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
STEP_COMPLETE(Worker 端, 含 url/title/dom_summary/visible_text)
  → Runtime 端:
    1. 提取 ObservationState(从 STEP_COMPLETE.payload 合并 dom_summary/visible_text)
    2. 合成 OBSERVE_COMPLETE 事件 → 发布到 EventBus(供 TimelineRecorder 等订阅)
    3. 合成 THINK_START 事件 → ReActEngine.decide() (基于 langchain 抽象)
    4. 合成 THINK_COMPLETE(含 reasoning/tokens_used)
    5. 映射 decision_type:
       → ACT:       CONTINUE(action) 发给 Worker
       → ASK_HUMAN: transition WAITING_USER, 发 INTERRUPT(reason="agent_ask_human", ask_human_*) 给 Worker
       → DONE:      STOP(TASK_FINISHED)
```

> 📌 **2026-06-11 修订**:原 V2.5 设计自造 ReActEngine,2026-06-11 决定改用 langchain 抽象(避免重复造)。具体实现路径:
> - 使用 `langchain.agents.create_react_agent(llm, tools, prompt)` 创建 ReAct agent
> - 用 `langchain.callbacks` 订阅 on_chain_start / on_chain_end 提取 reasoning / tokens
> - 工具定义:`@tool navigate / click / input_text / screenshot / extract / ask_human`,tool 调用失败 → ReAct agent 内部推理 fallback
> - LLM 失败 fallback 链:ReAct agent 内部 retry → PolicyEngine.decide() → regex URL 提取
> - 决策:`ReAct agent 输出` 映射到 `ReActDecisionType` (ACT/ASK_HUMAN/DONE)
>
> 自造一个 200 行的轻量 ReAct 循环看似简单,但 langchain 提供的 callbacks / memory / token 计数 / 中间件是必做能力(覆盖率 ≥ 80%),自造需要 500+ 行补丁。详见 `docs/assumptions.md` §A.1。

### 4.5.1 LangChain ↔ V2.5 桥接层(关键设计,P1-5)

**核心问题**(P1-5 提出):
1. LangChain `@tool` 默认同步,但 V2.5 全异步架构
2. LangChain AgentExecutor 期望 tool 返回 str,BrowserSkill 返回结构化 `ActionResult`
3. V2.5 的 observation 来自 `ObservationState`(STEP_COMPLETE 派生),不是 LangChain 默认的 tool 返回值流
4. ASK_HUMAN 是 tool 还是 agent stop condition?

**桥接设计** —— 三层结构:

```
┌─────────────────────────────────────────────────────┐
│ V2.5 Runtime (本项目代码)                            │
│  _run_task() 主循环                                   │
│    ↓                                                 │
│  ReActEngine.decide() ← 包装 LangChain 调用         │
│    ↓                                                 │
│  ┌─────────────────────────────────────────────┐    │
│  │ V2.5ReActBridge (本项目, ~80 行)             │    │
│  │  - 把 ObservationState 注入 LangChain prompt │    │
│  │  - 解析 LangChain output → DecisionResponse  │    │
│  │  - ASK_HUMAN 识别为 agent 终态(不循环)       │    │
│  └─────────────────────────────────────────────┘    │
│    ↓                                                 │
│  LangChain AgentExecutor (第三方)                    │
│    ↓                                                 │
│  LangChain Tools (@tool 装饰的 async coroutine)      │
│    ↓                                                 │
│  V2.5 BrowserSkill.execute() (本项目)                │
└─────────────────────────────────────────────────────┘
```

**关键决策 1: 自定义 AgentExecutor 而非默认**

V2.5 选**自定义 AgentExecutor 子类**而非默认实现,原因:
- 默认 AgentExecutor 在 tool 返回时把 result 当 observation 注入下一轮推理,但 V2.5 的 observation 来自 `ObservationState`(STEP_COMPLETE 派生),不是 tool 返回值
- 自定义子类在 `._take_next_step()` 钩子里**跳过** tool result → observation 的自动注入,改为手动把 `ObservationState` 写入 agent_scratchpad

```python
# runtime/react_bridge.py
from langchain.agents import AgentExecutor
from langchain.agents.react.base import ReActDocstoreAgent

class V25ReActExecutor(AgentExecutor):
    """V2.5 定制 AgentExecutor —— 手动管理 observation 注入

    默认 AgentExecutor 行为: tool 返回 → 注入 scratchpad → 下一轮
    V2.5 行为: tool 返回 → 跳过注入 → 等 Runtime 收到 STEP_COMPLETE →
    合成 ObservationState → 显式调用 _inject_observation() → 下一轮
    """
    def _take_next_step(self, name_to_tool_map, color_mapping, inputs, ...):
        # 复用父类逻辑执行 tool
        step_output = super()._take_next_step(...)
        # 关键差异: tool 完成后,父类默认会立即把 tool_result 拼接到 scratchpad
        # 我们在 _call() 入口主动设置 self._pending_observation,
        # 这里只保留 tool 调用结果,但不让 agent 立即看到 observation
        return step_output
```

**关键决策 2: Tool 定义用 async coroutine**

```python
# runtime/react_tools.py
from langchain.tools import tool
from app.worker.skill import SkillRegistry  # V2.5 已有

@tool
async def navigate(url: str) -> str:
    """导航到指定 URL。参数:url 完整 URL(含 https://)"""
    skill = SkillRegistry.get("browser")
    result = await skill.execute(ActionDetail(
        type="navigate", target=url, description=f"导航到 {url}"
    ))
    return result.to_brief_string()    # 转字符串给 LangChain 内部用

@tool
async def ask_human(block_type: str, question: str) -> str:
    """[特殊 tool] 向用户求助,会中断任务。block_type: login|captcha|paywall|consent|other"""
    # 这个 tool 不真正执行任何动作 —— V25ReActExecutor 检测到 tool name == 'ask_human'
    # 时立即终止 agent loop,设置 self._ask_human_payload,
    # Runtime 检测到后转 WAITING_USER
    raise AskHumanInterrupt(block_type=block_type, question=question)
```

**关键决策 3: ASK_HUMAN 是 stop condition,不是普通 tool**

`ask_human` tool 在 V25ReActExecutor 中被**特殊处理**:
- 正常 tool(click/navigate/...) → 同步执行 → result 进 scratchpad → 下一轮推理
- `ask_human` tool → 抛 `AskHumanInterrupt` 异常 → executor 捕获 → 终止 loop → 标记为 `decision_type=ASK_HUMAN`
- 不进入下一次 ReAct 循环,避免"LLM 问完用户又继续想别的" 的死循环

**关键决策 4: Token 计数和 latency 通过 callback 提取**

```python
# runtime/react_callbacks.py
from langchain.callbacks.base import BaseCallbackHandler
from app.infra.event_bus import EventBus
from app.runtime.protocol.types import EventType, RuntimeEvent

class RuntimeBridgeCallback(BaseCallbackHandler):
    """把 LangChain 内部事件翻译成 V2.5 RuntimeEvent

    所有 LangChain 事件通过这个 callback 桥接到 V2.5 事件总线,
    TimelineRecorder 等订阅者无需修改,保持统一事件源。
    """
    def __init__(self, event_bus: EventBus, task_id: str) -> None:
        self._event_bus = event_bus
        self._task_id = task_id
        self._llm_start_time: float = 0.0

    def on_llm_start(self, serialized, prompts, **kwargs):
        self._llm_start_time = time.monotonic()
        self._event_bus.publish(RuntimeEvent(
            event=EventType.THINK_START,
            task_id=self._task_id,
            payload={"step_index": self._step_index},
        ))

    def on_llm_end(self, response, **kwargs):
        # 提取 token 消耗 + reasoning 文本
        llm_latency_ms = int((time.monotonic() - self._llm_start_time) * 1000)
        tokens_used = response.llm_output.get("token_usage", {}).get("total_tokens", 0)
        reasoning = response.generations[0][0].text
        self._event_bus.publish(RuntimeEvent(
            event=EventType.THINK_COMPLETE,
            task_id=self._task_id,
            payload={
                "step_index": self._step_index,
                "reasoning": reasoning,
                "tokens_used": tokens_used,
                "llm_latency_ms": llm_latency_ms,
            },
        ))
```

**ReActEngine.decide() 内部实现**(组装上述组件):

```python
# runtime/react_engine.py (部分)
from langchain.agents import create_react_agent
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from .react_bridge import V25ReActExecutor
from .react_tools import navigate, click, input_text, screenshot, extract, ask_human
from .react_callbacks import RuntimeBridgeCallback

class ReActEngine:
    def __init__(self, llm: ChatLLM, event_bus: EventBus, *, model: str | None = None):
        self._llm = llm
        self._event_bus = event_bus
        self._model = model or os.getenv("REACT_MODEL", "deepseek-v4-pro")

        # 工具列表(本项目 V2.5 已有 BrowserSkill,直接包成 LangChain tool)
        self._tools = [navigate, click, input_text, screenshot, extract, ask_human]

        # ReAct prompt(从 §4.4 读取)
        self._prompt = PromptTemplate.from_template(_REACT_PROMPT_TEMPLATE)

        # 自定义 AgentExecutor(关键)
        self._agent = create_react_agent(self._llm, self._tools, self._prompt)

    async def decide(
        self,
        goal: str,
        trajectory: Trajectory,
        observation: ObservationState,
    ) -> DecisionResponse:
        callback = RuntimeBridgeCallback(self._event_bus, task_id="...")

        executor = V25ReActExecutor(
            agent=self._agent,
            tools=self._tools,
            verbose=False,
            max_iterations=10,        # 防止 LLM 死循环
            handle_parsing_errors=True,
        )

        try:
            # 注入 observation 作为初始输入的一部分
            # AgentExecutor 内部把 input + scratchpad 拼成完整 prompt
            result = await executor.ainvoke(
                {
                    "input": _format_observation(observation),  # 把 ObservationState 转 LangChain 格式
                    "goal": goal,
                    "trajectory_summary": trajectory.summary_for_prompt(),
                },
                config={"callbacks": [callback]},
            )
        except AskHumanInterrupt as e:
            # ask_human tool 触发的中断 → 映射成 ASK_HUMAN 决策
            return DecisionResponse(
                decision_type="ASK_HUMAN",
                block_type=e.block_type,
                question=e.question,
                reasoning="Agent 主动求助(LLM 推理认为需要人类介入)",
            )

        # ACT 路径: result 是 LangChain AgentExecutor 输出,需要解析
        return _parse_langchain_output(result)
```

**为什么需要 _format_observation() 和 _parse_langchain_output()**:
- `_format_observation()`: LangChain 期望 dict 输入,需要把 `ObservationState(url, title, dom_summary, ...)` 渲染成 `{"observation": "...", "url": "...", ...}` 喂给 prompt
- `_parse_langchain_output()`: LangChain AgentExecutor 输出 `{"output": "...", "intermediate_steps": [...]}`,需要把 `intermediate_steps[-1][0].tool_input` 还原成 V2.5 `ActionDetail`

> 📌 **2026-06-11 修订**(P1-5):原 §4.5 只提"用 langchain callbacks" 一句,缺失 4 个关键设计: AgentExecutor 自定义 / tool 异步 / observation 注入 / ASK_HUMAN 终止语义。补全后实现路径明确,不再"文档没说"。

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

**YOLO 模式与 NEED_HUMAN 的语义约定**(V2.5 明确):

| RunMode | NEED_HUMAN(能力边界) | NEED_CONFIRM(风险确认) | 行为 |
|---|---|---|---|
| **SEMI**(半自动) | 触发 → 转 WAITING_USER | 触发 → 转 WAITING_CONFIRM | 默认行为,V2.5 推荐 |
| **YOLO**(全自动) | **仍触发 → 转 WAITING_USER**(能力边界无法用"全自动"绕过) | **不触发 → 当 ACT 处理**(风险操作自动执行) | YOLO 是"无需风险确认",不是"无需能力补全" |

**为什么 YOLO 也要触发 NEED_HUMAN**:
- YOLO 语义是"全自动,不需要人工**确认**",不是"全自动,不需要人工**能力**"
- 登录凭据/验证码本质上是**缺失信息**,不是"高风险操作",无法用"全自动"绕过
- YOLO 模式下遇到登录页面,Agent 必须停下来等用户提供凭据,**否则会陷入死循环**(已设计 LLM prompt 明确"Do NOT attempt to brute-force logins")
- 风险操作(发布/支付)才是 YOLO 应该"全自动"的部分

> 📌 **2026-06-11 修订**:原 V2.5 设计 §12.1 写"YOLO 模式下可以跳过 ASK_HUMAN(全部当 ACT 处理)",与 LLM prompt 约束"不暴力登录"矛盾。明确:YOLO 仅跳过 NEED_CONFIRM,不跳过 NEED_HUMAN。

---

## 5. 用户中途插话(Human-in-the-loop)

### 5.1 两种场景

| 场景 | 发起方 | 协议流 |
|---|---|---|
| **Agent 求助** | Agent(ReActEngine) | ReActEngine → NEED_HUMAN → WAITING_USER → 用户 POST /tasks/{id}/messages → RESUME → ReActEngine 重新规划 |
| **用户主动中断** | User | 用户 POST /tasks/{id}/messages → INTERRUPT → Worker 暂停 → WAITING_USER → 用户输入 → RESUME → ReActEngine 重新规划 |

### 5.2 Worker INTERRUPT 处理

`worker/worker_session.py` 主循环新增(基于 §3.2 明确语义):

```python
# 状态变量(在 WorkerSession.__init__ 中初始化)
self._interrupt_requested: bool = False    # INTERRUPT 标志:放弃当前 step
self._pause_after_step: bool = False       # PAUSE 标志:完成当前 step 后停

# 主循环 dispatch
elif command.type == CommandType.INTERRUPT:
    self._interrupt_requested = True
    self._worker_status = WorkerStatus.WAITING_USER    # 📌 V2.5 修订: 新增 WorkerStatus.WAITING_USER
    emit_event(RuntimeEvent(event=EventType.INTERRUPTED, ...))
    # 回到主循环顶,等待 RESUME 或 STOP(不立即发 STEP_COMPLETE)
    # _execute_action() 检查 _interrupt_requested 后直接 return

elif command.type == CommandType.RESUME:
    self._interrupt_requested = False
    self._pause_after_step = False
    self._worker_status = WorkerStatus.RUNNING
    emit_event(RuntimeEvent(event=EventType.RESUMED, ...))
    # Runtime 会在之后发 CONTINUE 带新动作

elif command.type == CommandType.PAUSE:
    self._pause_after_step = True
    self._worker_status = WorkerStatus.WAITING_USER    # 📌 V2.5 修订: PAUSE 也用 WAITING_USER(避免歧义)
    # 标志位,_execute_action() 返回前检查,完成当前 STEP_COMPLETE 后挂起
```

**WorkerStatus 枚举扩展**(`backend/app/runtime/protocol/types.py` 改造):

```python
class WorkerStatus(StrEnum):
    """Worker 自身状态 —— 通过 WORKER_HEARTBEAT 上报"""
    IDLE = "idle"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"   # V1: 等用户对 NEED_CONFIRM 响应
    WAITING_USER = "waiting_user"         # 📌 V2.5 新增: 等用户对 NEED_HUMAN/INTERRUPT/PAUSE 响应
```

**为什么新增 WAITING_USER 而不是复用 WAITING_CONFIRM**:
- WAITING_CONFIRM = 风险操作"是否执行"的二元确认(Reject → STOP,Approve → RUN)
- WAITING_USER = 能力边界/中断等待用户输入(文本反馈后 → ReActEngine 重新规划)
- 心跳/监控场景下,RUNTIME 收到 WAITING_USER 能区分"用户没看到确认弹窗"vs"用户没看到求助弹窗",告警策略不同

> 📌 **2026-06-11 修订**(P0-1):原 §5.2 INTERRUPT/PAUSE 都设 `WAITING_CONFIRM`,Runtime 侧无法区分"等风险确认"还是"等用户输入",会导致告警/重连策略错误。新增 `WorkerStatus.WAITING_USER` 解决。

**`_execute_action()` 重构**(V2.5 修复 step_count 一致性 + 明确 INTERRUPT/PAUSE 行为 + 修复 STEP_START 空洞):

```python
async def _execute_action(self, action: ActionDetail, skill_name: str) -> None:
    # 步骤开始前:检查 INTERRUPT/PAUSE 标志(避免已自增但被中断导致序号不一致)
    if self._interrupt_requested or self._pause_after_step:
        # 不自增,不发射 STEP_START,不执行
        # Runtime 会重新发 CONTINUE(PAUSE 恢复) 或等待用户响应(INTERRUPT 恢复)
        return

    self._step_count += 1
    self._emit_step_start(self._step_count, action.type, action.description)

    result = await skill.execute(action)

    # INTERRUPT 检查(在 _emit_step_complete 之前)
    if self._interrupt_requested:
        # 📌 V2.5 修复 STEP_START 空洞(P0-2):
        # 不能让 Timeline 出现"开始但未完成"的步骤,
        # 发 STEP_COMPLETE(aborted=True) 闭合步骤
        self._emit_step_complete(
            self._step_count,
            duration_ms=int((time.monotonic() - self._step_start_time) * 1000),
            aborted=True,                                # 📌 关键标志
            abort_reason="user_interrupt",               # user_interrupt | agent_ask_human | system
        )
        log.info("worker.step_aborted_by_interrupt", step=self._step_count)
        return

    # PAUSE 检查(在 _emit_step_complete 之前)
    if self._pause_after_step:
        # 完成当前 step:发 STEP_COMPLETE 然后挂起
        self._emit_step_complete(self._step_count, aborted=False)
        self._worker_status = WorkerStatus.WAITING_USER
        return  # 回到主循环顶,等 RESUME

    # 正常路径
    self._emit_step_complete(self._step_count, aborted=False)
```

**为什么用 `aborted=true` 而不是不发 STEP_COMPLETE**(P0-2 方案选择):
- **方案 A(采用)**: STEP_COMPLETE 照常发,带 `aborted=true` 标志。TimelineRecorder 写入 task_steps 时 `step_type='act'`,`status='aborted'`,前端 Timeline 渲染为灰色"已中止"步骤,用户能明确看到"这一步被中断了"
- **方案 B(否决)**: 不发 STEP_COMPLETE。优点是 Timeline 简洁;缺点是"步骤开始→间隔很久→用户中断"无任何痕迹,排查"为什么任务没完成"时 grep 不到
- **方案 C(否决)**: 发 STEP_ABORTED 新事件类型。语义清晰但增加协议复杂度,V2.5 不值得

**StepCompletePayload 扩展字段**:

```python
class StepCompletePayload(BaseModel):
    # ... 现有字段 ...
    aborted: bool = False              # 📌 V2.5 新增: True = 步骤被 INTERRUPT 强制中止
    abort_reason: str = ""             # 📌 V2.5 新增: user_interrupt | agent_ask_human | system
```

**task_steps 写入语义**(TimelineRecorder 侧):

| aborted | step_type | 渲染 |
|---|---|---|
| False | observe/think/act/human | 正常步骤 |
| True | act(灰色) | 已中止步骤(用户/系统主动中断) |

> 📌 **2026-06-11 修订**(P0-2):原 §5.2 INTERRUPT 路径"不发 STEP_COMPLETE"会导致 Timeline 出现"开始但未完成" 的空洞,前端无法渲染也难以排查。改为"发 STEP_COMPLETE(aborted=true)" 后,Timeline 始终成对(START↔COMPLETE),前端可灰显"已中止"步骤。

**关键设计点**(V2.5 明确):

1. **step_count 自增时机**:在 `if self._interrupt_requested` 检查**之后**;被中止的 action **占** step_count,但 STEP_COMPLETE 带 `aborted=true` 标记(这样 Runtime 端 Trajectory 序号与 Worker 端一致)
2. **STEP_START 发射时机**:与 step_count 自增同步;**STEP_COMPLETE 总是成对发射**,保证 Timeline 无空洞(被中止也发)
3. **INTERRUPT 与 PAUSE 互斥**:同一时刻只有一个标志位为 True(Runtime 不会同时发两个命令)
4. **PAUSE 路径 STEP_COMPLETE.aborted=False**:因为是"完成当前步",不是"放弃"
5. **INTERRUPT 路径 STEP_COMPLETE.aborted=True**:用户/Agent 主动放弃的步骤,前端灰显

> 📌 **2026-06-11 修订**:原 V2.5 设计 `_execute_action()` 流程是 `step_count += 1` → `emit_step_start` → `skill.execute` → `if self._interrupted: return`,会导致"已自增但不发 STEP_COMPLETE" 的序号不一致问题(原 §5.2 备注"不发射 STEP_COMPLETE" 也与"立即中断"语义冲突)。重排为"先检查标志 → 再自增 → 再执行 → 再检查标志" 后,语义清晰,STEP_COMPLETE 永远成对发射(必要时 aborted=true)。

### 5.3 send_task_message 增强(RUNNING/WAITING_USER 分流)

`app/api/tasks.py` 的 `send_task_message()` 按状态分流,**完全替代 V2.0 RUNNING 路径**(破坏性变更,理由见下):

```python
@router.post("/{task_id}/messages")
async def send_task_message(
    task_id: str,
    payload: TaskMessageCreate,
    user_id: UUID = Depends(get_current_user_id),
) -> TaskMessageOut:
    """用户向 Agent 发送指令 —— V2.5 完全替代 V2.0 实现

    V2.5 决策: RUNNING 状态下用户消息 100% 走 INTERRUPT 路径(不再"静默追加 feedback")
    理由: V2.0 的 CONTINUE(feedback) 路径让 LLM "悄悄考虑" 用户反馈, 用户不知道
    Agent 何时响应、是否会执行, UX 不一致。V2.5 统一为"用户发消息 = 中断当前任务"
    """
    current_state = _task_state_mgr.get_state(task_id)
    runner = _active_runners.get(task_id)

    if runner is None:
        log.warning("message.no_active_runner", task_id=task_id, state=current_state.value)
        return TaskMessageOut(...)  # 任务已结束,仅记录消息

    if current_state == TaskState.RUNNING:
        # V2.5: 用户中途插话 → INTERRUPT Worker(替代 V2.0 的 CONTINUE+feedback)
        cmd = Command(
            command_id=_new_cmd_id(),
            type=CommandType.INTERRUPT,
            payload={
                "reason": "user_interrupt",
                "user_message": payload.content,
            },
        )
        await _task_state_mgr.transition(
            task_id, TaskState.WAITING_USER, f"用户中断: {payload.content[:80]}"
        )
        await runner.send_command(cmd)
        log.info("message.user_interrupt", task_id=task_id, content=payload.content[:80])

    elif current_state == TaskState.WAITING_USER:
        # 用户回复 Agent 求助 或 继续中断
        # 从 task_state 上下文取上次的 ask_human_block_type(若有)
        prev_interrupt_payload = _task_state_mgr.get_context(task_id, "interrupt_payload", {})
        ask_human_block_type = prev_interrupt_payload.get("ask_human_block_type", "")
        ask_human_question = prev_interrupt_payload.get("ask_human_question", "")

        cmd = Command(
            command_id=_new_cmd_id(),
            type=CommandType.RESUME,
            payload={
                "feedback": payload.content,
                "ask_human_block_type": ask_human_block_type,  # 透传给 ReActEngine
                "ask_human_question": ask_human_question,
            },
        )
        await _task_state_mgr.transition(
            task_id, TaskState.RUNNING, f"用户回复: {payload.content[:80]}"
        )
        # ReActEngine 收到 RESUME 后重新 decide,然后发 CONTINUE
        await runner.send_command(cmd)
        log.info("message.user_resume", task_id=task_id, content=payload.content[:80])

    elif current_state == TaskState.WAITING_CONFIRM:
        # V2.5: 保留 V2.0 的 reject_keywords 启发式
        reject_keywords = {"拒绝", "取消", "不要", "no", "reject", "cancel", "stop"}
        is_reject = any(kw in payload.content.lower() for kw in reject_keywords)
        if is_reject:
            cmd = Command(type=CommandType.REJECT, payload={"reason": payload.content})
            # 📌 V2.5 修复 (P0-4):
            # REJECT 路径必须先 transition 到 STOPPING,再发命令。
            # 否则 Worker 收到 REJECT 后发 TASK_FINISHED 期间(网络/Worker 异常),
            # 状态机卡在 WAITING_CONFIRM 永不退出 —— 监控告警/前端 UI 错乱
            # 后续 transition(STOPPING → CANCELLED) 由 Worker TASK_FINISHED 事件触发
            await _task_state_mgr.transition(
                task_id,
                TaskState.STOPPING,
                f"用户拒绝: {payload.content[:80]}",
            )
        else:
            cmd = Command(
                type=CommandType.CONTINUE,
                payload={"approved": True, "feedback": payload.content},
            )
            await _task_state_mgr.transition(task_id, TaskState.RUNNING, f"用户确认: {payload.content[:80]}")
        await runner.send_command(cmd)

    # PAUSED / 终态: 拒绝(幂等返回 400)
    else:
        log.warning("message.task_not_accepting", task_id=task_id, state=current_state.value)
        raise HTTPException(400, f"任务状态 {current_state.value} 不接受消息")

    return TaskMessageOut(...)
```

**V2.0 → V2.5 行为变更**(破坏性,需前端适配):

| 任务状态 | V2.0 行为 | V2.5 行为 | 差异 |
|---|---|---|---|
| RUNNING | 发 `CONTINUE(feedback)` 让 PolicyEngine 考虑 | 发 `INTERRUPT` 转 WAITING_USER 等用户输入 | **行为破坏性变更** |
| WAITING_USER | 不存在该状态 | 收到消息发 `RESUME` 转 RUNNING | 新增状态 |
| WAITING_CONFIRM | 发 CONTINUE/REJECT(同 V2.5) | 同 V2.0 | 无变化 |

**前端迁移要求**(V2.5 PR4 必做):
- `ChatInput` 在 RUNNING 时显示"发送并暂停"按钮(不再是 disabled)
- 点击后状态立刻切到 WAITING_USER(由 Runtime 转)
- WAITING_USER 状态下显示"回复 Agent"输入框
- 不再支持"静默追加 feedback"

> 📌 **2026-06-11 修订**:原 V2.5 设计只说"RUNNING 状态发 INTERRUPT",未明确"是否替代 V2.0 的 CONTINUE+feedback 路径"。明确为"完全替代"后,语义统一(用户发消息=中断),但需要在 PR4 前端迁移中明确告知用户行为变更。

### 5.4 WAITING_USER 超时保护 + 上下文序列化

在 `_run_task()` 中,进入 WAITING_USER 后启动 300s 定时器:

```python
if decision.decision_type == "ASK_HUMAN":
    # 保存 ASK_HUMAN 上下文(供 resume 时回传 ReActEngine,见问题 #8)
    await _task_state_mgr.set_context(
        task_id,
        key="interrupt_payload",
        value={
            "ask_human_block_type": decision.ask_human_block_type,
            "ask_human_question": decision.ask_human_question,
        },
    )
    await _task_state_mgr.transition(task_id, TaskState.WAITING_USER, ...)

    # 等待用户响应(超时 300s)
    try:
        event = await asyncio.wait_for(event_queue.get(), timeout=300.0)
    except TimeoutError:
        # 📌 V2.5 修复 (P0-3):
        # 必须走 transition() 而不是直接 result_state = FAILED 后 break,
        # 否则 WAITING_USER → FAILED 状态转换的副作用(发 TASK_STATE_CHANGED 事件、
        # 通知 TimelineRecorder/监控)都被跳过,且 break 后会走"正常结束" 路径发 TASK_FINISHED,
        # 与 FAILED 语义冲突
        result_reason = "用户 300s 未响应 Agent 求助"
        await _task_state_mgr.transition(
            task_id,
            TaskState.FAILED,
            f"wait_user_timeout: {result_reason}",
        )
        # 序列化 Checkpoint(含 ASK_HUMAN 上下文,见下)
        if _checkpoint_manager is not None:
            await _checkpoint_manager.save_task_checkpoint(
                task_id=task_id,
                goal=context.goal,
                step_index=trajectory.step_index,
                trajectory_summary=trajectory.summary_for_prompt(),
                checkpoint_type="user_unresponsive",
                action_result=decision.ask_human_question,  # 供 resume 时前端提示
                pending_ask_human={
                    "block_type": decision.ask_human_block_type,
                    "question": decision.ask_human_question,
                },
            )
        # 跳出 _run_task 主循环,触发正常结束清理路径
        # (不发 TASK_FINISHED —— TASK_FINISHED 是 Worker 端协议事件,
        # Runtime 超时发的是 TASK_STATE_CHANGED 事件,Tasks API 监听该事件写终态)
        break
```

**为什么超时必须走 transition() 而不只是设 result_state**(P0-3 解释):
- `transition()` 副作用: 状态转换合法性校验 + 发 `TASK_STATE_CHANGED` 事件 + 通知所有订阅者(TimelineRecorder / 监控 / 前端 WebSocket)
- 直接 `result_state = FAILED` 然后 `break`: 绕过转换逻辑,前端只看到"TASK_FINISHED"(语义上是"完成")不是"FAILED",状态机视图错乱
- 后续 `resume_task()` 加载 checkpoint 后,会从 `state='failed'` 重新启动(不依赖 TASK_FINISHED),所以 break 后不需要发 TASK_FINISHED

> 📌 **2026-06-11 修订**(P0-3):原 §5.4 直接 `result_state = TaskState.FAILED; break`,跳过了 transition() 的副作用。改为先 `transition(WAITING_USER → FAILED)` 再 break,保证状态机一致性。

**CheckPointManager 扩展字段**(`backend/app/model/checkpoint.py` 改造):

```python
class Checkpoint(Base, UUIDMixin):
    __tablename__ = "checkpoints"
    # ... 现有字段 ...
    # V2.5 新增
    pending_ask_human: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 记录"用户未响应的 ask_human 上下文",resume 时还原到 Trajectory 头部
```

**Resume 后的 ReActEngine 重新规划**(V2.5 明确):

```python
# resume_task() 加载 checkpoint 后,ReActEngine.decide() 的输入变化
async def decide(goal, trajectory, observation, *, resume_context=None):
    if resume_context and resume_context.pending_ask_human:
        # 把 pending_ask_human 注入 prompt 的"RECENT BLOCKERS" 部分
        prompt = prompt.replace(
            "{recent_blockers}",
            f"Earlier you asked: {resume_context.pending_ask_human['question']} "
            f"(block_type={resume_context.pending_ask_human['block_type']}). "
            f"User didn't respond in 300s. Consider trying an alternative path."
        )
    # ... 正常 ReAct 循环
```

> 📌 **2026-06-11 修订**:原 V2.5 设计只说"超时后保存 checkpoint(可 resume)",但**checkpoint 不存 ASK_HUMAN 上下文,resume 后 ReActEngine 不知道"用户原本要回答什么"**。明确:checkpoint 加 `pending_ask_human` JSONB 字段,resume 时注入 ReActEngine prompt 的"RECENT BLOCKERS" 部分。

---

## 6. Agent 可观测增强

### 6.1 数据模型变更

#### task_steps 新增 9 列(全部 nullable)

| 列 | 类型 | 说明 |
|---|---|---|
| `duration_ms` | INTEGER | 步骤执行耗时(Worker 上报) |
| `llm_latency_ms` | INTEGER | LLM 调用延迟(Runtime 记录) |
| `tokens_prompt` | INTEGER | 输入 token 数 |
| `tokens_completion` | INTEGER | 输出 token 数 |
| `model_name` | VARCHAR(64) | 使用的模型(MiMo-V2.5 / deepseek-v4-pro 等) |
| `reasoning` | TEXT | ReAct 推理文本(think 步骤) |
| `step_type` | VARCHAR(16) DEFAULT 'act' | observe / think / act / human |
| `dom_summary` | TEXT | 📌 V2.5 新增:Worker 导航类动作后提取的 DOM 摘要 |
| `visible_text` | TEXT | 📌 V2.5 新增:Worker 导航类动作后提取的可见文本 |

#### tasks 新增 3 列

| 列 | 类型 | 说明 |
|---|---|---|
| `total_tokens` | INTEGER DEFAULT 0 | 任务总 token(prompt+completion) |
| `total_cost_usd` | NUMERIC(10,6) DEFAULT 0 | 任务总成本 |
| `llm_model_used` | VARCHAR(64) | 任务使用的模型 |

**`total_cost_usd` 累加职责**(V2.5 明确,见问题 #11):

| 写入点 | 职责 | 时机 |
|---|---|---|
| **TimelineRecorder 订阅 THINK_COMPLETE** | 累加 `total_tokens` / `total_cost_usd` 到 tasks 表 | 每次 ReActEngine.decide() 返回后 |
| TimelineRecorder 订阅 STEP_COMPLETE | 写 task_steps 单步记录(含 tokens_prompt/tokens_completion/model_name) | Worker 上报时 |
| ReActEngine.decide() | 调 calculate_cost() 算单次 LLM 成本,写入 THINK_COMPLETE.payload | LLM 调用后 |

**为什么 TimelineRecorder 负责累加,不在 ReActEngine**:
- TimelineRecorder 已经订阅 TASK_STATE_CHANGED / STEP_COMPLETE / ERROR,加 THINK_COMPLETE 是自然扩展
- ReActEngine 是"决策模块",与持久化解耦,只输出 DecisionResponse(不直接写 DB)
- 累加逻辑与现有 _write_step 复用同一个事务(原子性)

**累加 SQL 原子性保证**(P2-13 修订,避免 read-then-write 竞态):

```python
# runtime/timeline_recorder.py
from sqlalchemy import text

async def _accumulate_task_cost(self, task_id: UUID, delta_tokens: int, delta_cost_usd: float) -> None:
    """累加任务总成本 —— SQL 层原子操作,避免 read-then-write 竞态

    📌 V2.5 修复 (P2-13):
    原设计 read-then-write 模式:
        current = SELECT total_cost_usd FROM tasks WHERE id = :task_id
        new_value = current + delta
        UPDATE tasks SET total_cost_usd = :new_value
    这种模式在多 worker / 重连场景下会有 lost update 问题:
    Worker A 读 0.05,Worker B 读 0.05,A 写 0.06,B 写 0.07 → 实际应该是 0.08

    改为 SQL 原子累加,单条 UPDATE 即可:
    """
    stmt = text("""
        UPDATE tasks
        SET total_tokens = total_tokens + :delta_tokens,
            total_cost_usd = total_cost_usd + :delta_cost_usd,
            llm_model_used = COALESCE(:model_name, llm_model_used)
        WHERE id = :task_id
    """).bindparams(
        task_id=task_id,
        delta_tokens=delta_tokens,
        delta_cost_usd=delta_cost_usd,
        model_name=self._last_model_used,    # 记录最后使用的模型
    )
    await self._session.execute(stmt)
    # 同一事务内 await self._session.commit() 在调用方完成
```

**ReAct 串行性前提被打破时的防御**(P2-13 风险评估):
- **正常情况**: ReAct 决策是串行的(同一 task 同一时刻只跑一次 LLM),不会并发累加
- **异常情况**:
  1. Runtime 重启后,从 checkpoint 恢复后第一个 THINK_COMPLETE 与尚未持久化的旧 THINK_COMPLETE 重发 → 并发累加
  2. Worker 重连后,Runtime 把"Worker 漏发的 STEP_COMPLETE" 重放给 TimelineRecorder → 并发累加
  3. 多个 Runtime 实例处理同一 task(理论不该发生,但重连 / failover 可能短暂出现)
- **SQL 原子累加防御**: 即使异常情况下并发执行,`total_cost_usd = total_cost_usd + :delta` 在 PG 行级锁保护下是原子的,不会出现 lost update
- **额外防御**: `tasks` 表加行级 `SELECT ... FOR UPDATE` 在 TimelineRecorder 入口,但会降低吞吐。V2.5 暂不引入,SQL 原子累加已足够

> 📌 **2026-06-11 修订**(P2-13):原 §6.1 TimelineRecorder 累加 total_cost_usd 用 read-then-write 模式,正常 ReAct 串行下没问题,但 Runtime 重启/重连场景下可能出现 lost update。改为 SQL `SET total = total + :delta` 原子累加后,任何并发场景都安全。

### 6.2 迁移

单次 Alembic 迁移,原子事务:

```sql
-- task_steps: 9 列(全部 nullable,不阻塞现有写路径)
ALTER TABLE task_steps ADD COLUMN duration_ms INTEGER;
ALTER TABLE task_steps ADD COLUMN llm_latency_ms INTEGER;
ALTER TABLE task_steps ADD COLUMN tokens_prompt INTEGER;
ALTER TABLE task_steps ADD COLUMN tokens_completion INTEGER;
ALTER TABLE task_steps ADD COLUMN model_name VARCHAR(64);
ALTER TABLE task_steps ADD COLUMN reasoning TEXT;
ALTER TABLE task_steps ADD COLUMN step_type VARCHAR(16) DEFAULT 'act';
ALTER TABLE task_steps ADD COLUMN dom_summary TEXT;       -- 📌 V2.5 新增
ALTER TABLE task_steps ADD COLUMN visible_text TEXT;      -- 📌 V2.5 新增

-- tasks: 3 列(有 DEFAULT,不阻塞现有写路径)
ALTER TABLE tasks ADD COLUMN total_tokens INTEGER DEFAULT 0;
ALTER TABLE tasks ADD COLUMN total_cost_usd NUMERIC(10,6) DEFAULT 0;
ALTER TABLE tasks ADD COLUMN llm_model_used VARCHAR(64);

-- 索引 1: task_steps 按 step_type 过滤(think/human 步骤查询)
CREATE INDEX idx_task_steps_step_type ON task_steps(step_type)
    WHERE step_type IN ('think', 'human');

-- 📌 V2.5 新增 索引 2: stats 聚合查询(见问题 #10)
-- WHERE user_id = :user_id AND created_at >= :window_start
-- 现有 tasks 表只有 user_id 单列索引,大表下 created_at filter 会慢
CREATE INDEX idx_tasks_user_created_at ON tasks(user_id, created_at DESC);

-- 📌 V2.5 新增 索引 3: agents 状态过滤(任务创建时校验 agent.status='active')
CREATE INDEX idx_agents_status ON agents(status)
    WHERE status = 'active';

-- 📌 V2.5 新增 索引 4: task_steps 步骤耗时百分位查询
CREATE INDEX idx_task_steps_step_type_duration ON task_steps(step_type, duration_ms)
    WHERE duration_ms IS NOT NULL;
```

> 📌 **2026-06-11 修订**:原 V2.5 设计 §6.6 stats SQL 用 `COUNT(*) FILTER (WHERE user_id = :user_id AND created_at >= ...)`,但**没有对应联合索引**。PG 在 user_id 单列索引下做 created_at filter,百万行后会慢。补 `idx_tasks_user_created_at` 联合索引后,即使百亿行也能走 Index Scan。

### 6.2.1 现有 V2.0 `duration_ms` 字段(澄清)

V2.0 [schemas.py:76](backend/app/runtime/protocol/schemas.py#L76) 中 `StepCompletePayload.duration_ms: int | None = None` 已定义,但 V2 Worker 未发。V2.5 真正填充(Worker 上报)。

| 字段 | V2.0 状态 | V2.5 状态 |
|---|---|---|
| `duration_ms` | 已定义,V2 Worker 未发(总是 None) | Worker 上报,TimelineRecorder 写入 |
| `dom_summary` | 不存在 | 📌 V2.5 新增 |
| `visible_text` | 不存在 | 📌 V2.5 新增 |

### 6.3 LLM 成本计算(纯函数,定价表外置 P1-8)

**📌 V2.5 修订**(P1-8):定价表从代码常量移到 `core/config/llm_pricing.yaml`,支持**运行时更新**(模型调价不需要重新部署)。

**`core/config/llm_pricing.yaml`**(V2.5 新增):

```yaml
# LLM 模型定价表 (单位: USD per 1M tokens)
# 维护: SRE 在仓库内修改 → 走 PR 流程 → 配置中心拉取 → 进程内热重载
# 上次更新: 2026-06-11
version: "1.0"
models:
  deepseek-v4-flash: {input: 0.14, output: 0.28}
  deepseek-v4-pro: {input: 0.55, output: 1.10}
  mimo-v2: {input: 0.10, output: 0.20}
  mimo-v2.5: {input: 0.10, output: 0.20}
  gpt-4o: {input: 2.50, output: 10.00}
  gpt-4o-mini: {input: 0.15, output: 0.60}
  # 缺省定价(任何未列出模型 fallback 到这)
  _default: {input: 0.0, output: 0.0}
```

**`service/cost.py`**(从 YAML 读,支持热重载):

```python
# service/cost.py
import os
from pathlib import Path
import yaml
from app.core.logger import log

_PRICING_PATH = Path(os.getenv("LLM_PRICING_PATH", "core/config/llm_pricing.yaml"))
_pricing_cache: dict[str, tuple[float, float]] = {}
_pricing_mtime: float = 0.0

def _load_pricing(force: bool = False) -> dict[str, tuple[float, float]]:
    """读定价表,YAML 文件 mtime 变化时自动重载(实现热更新)

    性能: 每次 calculate_cost() 调用前检查 mtime,O(1) stat 调用,
    只有 mtime 变化才重新解析 YAML(几十 KB,毫秒级)
    """
    global _pricing_cache, _pricing_mtime

    if not _PRICING_PATH.exists():
        log.warning("cost.pricing_file_missing", path=str(_PRICING_PATH))
        return {}

    current_mtime = _PRICING_PATH.stat().st_mtime
    if not force and current_mtime == _pricing_mtime and _pricing_cache:
        return _pricing_cache

    with _PRICING_PATH.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    _pricing_cache = {
        model: (prices["input"], prices["output"])
        for model, prices in raw.get("models", {}).items()
    }
    _pricing_mtime = current_mtime
    log.info("cost.pricing_reloaded", models=len(_pricing_cache), version=raw.get("version"))
    return _pricing_cache

def calculate_cost(model: str, tokens_prompt: int, tokens_completion: int) -> float:
    """计算 LLM 调用成本

    - 不匹配的 model → 返回 _default 定价(0.0)
    - YAML 文件缺失 → 返回 0.0(不抛异常,避免阻断任务)
    - 性能: mtime 缓存命中时 O(1) 不读盘
    """
    pricing = _load_pricing()
    input_price, output_price = pricing.get(model, pricing.get("_default", (0.0, 0.0)))
    cost = (tokens_prompt / 1_000_000) * input_price + \
           (tokens_completion / 1_000_000) * output_price
    return round(cost, 6)
```

**为什么用 YAML + mtime 热重载而不是数据库**(P1-8 设计选择):
- **YAML 优势**: 简单可读,git diff 友好,PR review 直观,误改风险低
- **mtime 热重载**: SRE `kubectl exec` 改文件后无需重启 Runtime,下一个 LLM 调用时自动重载
- **不用数据库**: 定价变更频率低(月度级),不需要事务/审计;每次 LLM 调用都查 DB 引入 1-2ms 延迟
- **不用环境变量**: 环境变量只接受字符串,无法表达嵌套结构(多模型 + 缺省值),改起来也容易"环境漂移"

**更新流程**:
1. SRE 修改 `core/config/llm_pricing.yaml` 并提 PR
2. Code Review → merge
3. CI 自动 sync 到所有 Runtime 实例的 `LLM_PRICING_PATH`(configmap 挂载)
4. 下一个 LLM 调用时,Runtime 检测到 mtime 变化,自动 reload

**为什么不走配置中心(如 Apollo/Nacos)**:
- 学生项目,不引入额外中间件依赖
- mtime 重载是 80% 场景的简单实现
- 真正走配置中心可以放到 Phase 9 治理

> 📌 **2026-06-11 修订**(P1-8):原 §6.3 把 `_MODEL_PRICING` 硬编码在 Python 代码里,模型调价需要重新部署 Runtime。改为 YAML + mtime 热重载后,运营侧独立完成定价变更,符合"工程规范优于 Demo 能跑"。

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

### 6.5 Redis 指标缓存(失效语义修正)

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

    async def invalidate(self, agent_id: UUID) -> None:
        """失效单个 agent 的指标缓存

        📌 V2.5 修订: 取消"任务完成时调用 invalidate" 的全局失效语义
        改用 "Task 完成 → 解析出 agent_id → 失效该 agent 的缓存"
        避免多任务并发完成时,Task-A 完成把 Task-B 刚写入的有效缓存也清掉
        """
        key = f"agent_metrics:{agent_id}"
        await self._redis.delete(key)
```

**失效触发链**(V2.5 明确,见问题 #12):

| 事件 | 缓存动作 | 原因 |
|---|---|---|
| `GET /agents/{id}` 缓存命中 | 无 | 60s 内重复读 |
| `GET /agents/{id}` 缓存未命中 | 读 DB → 写缓存(60s TTL) | 第一次拉 |
| `POST /agents/{id}/pause` 或 `resume` | **立即失效该 agent 缓存** | 状态变化,旧缓存过期 |
| **Task 完成**(COMPLETED/FAILED/CANCELLED) | **只失效该 task 关联的 agent 缓存**(不是全部) | 多任务并发时不互相污染 |

**Task 完成时的失效调用**(在 TimelineRecorder._on_task_finished):

```python
async def _on_task_finished(self, event: RuntimeEvent) -> None:
    # 1. 写 task_steps 终态
    # 2. 写 tasks 表 status
    # 3. 📌 V2.5 新增: 失效该 task 的 agent 指标缓存
    if _metrics_cache is not None:
        task = await TaskRepository(session).get_by_id(task_uuid)
        if task and task.agent_id:
            await _metrics_cache.invalidate(task.agent_id)
```

> 📌 **2026-06-11 修订**:原 V2.5 设计 §6.5 写"任务完成时调用 invalidate" 但**没指明 invalidate 的粒度**,实现时容易做"清除所有缓存" 导致并发任务互相污染。明确"按 agent_id 单点失效" 后,多任务并发场景下每个 agent 的缓存独立维护。

### 6.6 Dashboard Stats SQL 重构(P2-12 参数化)

当前 `stats.py` 用 Python 过滤(list_by_user + for 循环),数据量大时无法接受。改为:

```sql
-- 全部时间窗口用参数 :window_start 注入(P2-12 修订)
-- 由 Python 层在调用前用 datetime.now() - timedelta 计算后传入
SELECT
  COUNT(*) FILTER (WHERE created_at >= :window_start) AS tasks_today,
  COUNT(*) FILTER (WHERE status = 'running') AS running,
  COALESCE(SUM(total_tokens) FILTER (WHERE created_at >= :window_start), 0) AS tokens_today,
  COALESCE(SUM(total_cost_usd) FILTER (WHERE created_at >= :window_start), 0) AS cost_today,
  COUNT(*) FILTER (WHERE status IN ('completed','failed','cancelled')
    AND updated_at >= :window_start) AS terminal_24h,
  COUNT(*) FILTER (WHERE status = 'completed'
    AND updated_at >= :window_start) AS success_24h
FROM tasks
WHERE user_id = :user_id;
```

**Python 调用层示例**:

```python
# api/stats.py
from datetime import datetime, timedelta, timezone

async def get_dashboard_stats(user_id: UUID, window_hours: int = 24) -> dict:
    window_start = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    # SQLAlchemy text() 参数绑定
    stmt = text("""
        SELECT
            COUNT(*) FILTER (WHERE created_at >= :window_start) AS tasks_today,
            ...
        FROM tasks
        WHERE user_id = :user_id
    """).bindparams(user_id=user_id, window_start=window_start)

    row = (await session.execute(stmt)).one()
    return dict(row._mapping)
```

**为什么必须参数化 :window_start 而不是 `NOW() - INTERVAL '24 hours'`**(P2-12 解释):
- **避免计划缓存失效**: PG 的 prepared statement 计划缓存按 SQL 文本 hash 缓存,`NOW()` 每次执行值不同 → 文本不变但语义有差异,缓存命中率低;参数化后计划可复用
- **可测试性**: 测试时可以注入任意 `window_start`,验证"7 天数据" / "30 天数据" / "自定义时间窗口" 的查询
- **统一客户端时间**: 所有 Runtime 实例的"现在" 略有差异(时钟漂移),由调用方统一传入,跨实例一致
- **SQL 注入防御**: 虽然 `INTERVAL '24 hours'` 看起来安全,但若后续改为 `INTERVAL :user_input_hours`,会立即有注入风险;提前参数化更稳妥

**一次返回所有仪表盘卡片数据,无需 Python 过滤**。

---

## 7. Agent 启停控制

### 7.1 状态机(AgentStatus,与 TaskState 命名空间分离)

```
ACTIVE ──drain──→ DRAINED ──activate──→ ACTIVE
  │                 │
  └──deprecated     └──(running tasks complete, new tasks rejected)
```

**为什么用 DRAINED 而不是 paused**:见 §3.3 命名空间分离说明。Kubernetes 业界术语,与 `TaskState.PAUSED` 区分。

### 7.2 Task 创建时的 Agent 状态校验

`app/api/tasks.py` 的 `create_task()` 中,在 `_resolve_default_agent_id()` 之后增加:

```python
# 校验 agent 是否 ACTIVE(V2.5 agent 生命周期)
if _pg_client is not None and agent_id is not None:
    session = _pg_client.session()
    try:
        from app.repository.agent import AgentRepository
        agent = await AgentRepository(session).get_by_id(agent_id)
        if agent is None:
            raise HTTPException(404, f"Agent {agent_id} not found")
        if agent.status != AgentStatus.ACTIVE.value:
            raise HTTPException(
                409, f"Agent is {agent.status}, cannot accept new tasks"
            )
    finally:
        await session.close()
```

### 7.3 多租户 / Ownership(Phase 9 必修,V2.5 暂标注)

**V2.5 现状**: `agents` 表无 `owner_id` / `tenant_id` 字段(V2.0 引入时为单租户,所有 agent 全局共享)。

**V2.5 决策**:
- V2.5 范围**不做 ownership 校验**(保持 V2.0 行为)
- **但** `POST /agents/{id}/pause` / `resume` 端点需在 V2.5 加 `user_id` 鉴权检查(防止误用),失败返回 403
- Phase 9 多租户阶段补:
  - `agents` 表加 `owner_id` FK
  - 现有 `browser-agent-default` 自动分配给 V2.5 期间所有用户
  - `create_task` 加 `agent.owner_id == user_id` 校验

**为什么不现在做**:
- V2.5 主线是 ReAct + 人机协作 + 可观测,ownership 是独立工作量(涉及 seed 迁移 + 鉴权中间件 + UI)
- 现在加会拖延 V2.5 4 PR 的进度
- 标注为"已知缺口",Phase 9 跟踪

> 📌 **2026-06-11 修订**:原 V2.5 设计 §7.2 只校验 `agent.status == "active"`,**没讨论多租户场景下是否校验 agent 归属**。明确:V2.5 范围标"暂不做 ownership" + Phase 9 跟踪,避免"留白"导致未来补全时缺乏上下文。

### 7.4 前端影响

- Agent 列表: ACTIVE 的 agent 出现在任务创建下拉中,DRAINED 的不出现
- Agent 卡片: 增加 drain/activate 操作按钮(仅 Dashboard 可见,显示为"Drain" / "Activate" 而不是 "Pause" / "Resume")
- 新建任务: 选 DRAINED agent 返回 409,前端展示错误提示

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

## 9. 实施阶段(4 PR,P3-17 拆分依据)

| PR | 内容 | 风险 | 预计文件 | 核心文件清单 |
|---|---|---|---|---|
| **PR1: 协议+数据层** | Protocol 枚举/payload + alembic 迁移 + model/schema 列新增 + 状态转换更新 | 低(纯数据) | 10 | `protocol/types.py` / `protocol/schemas.py` / `protocol/transitions.py` / `protocol/constants.py` / `model/task.py` / `model/task_step.py` / `model/checkpoint.py` / `model/agent.py` / `service/cost.py` / `core/config/llm_pricing.yaml` |
| **PR2: ReAct 引擎+API** | ReActEngine + bridge/tools/callbacks + _run_task 改造 + TimelineRecorder think 订阅 + agent detail/metrics/pause/resume 端点 + stats SQL 重构 | 中(决策逻辑) | 13 | `runtime/react_engine.py`(新)/ `runtime/react_bridge.py`(新)/ `runtime/react_tools.py`(新)/ `runtime/react_callbacks.py`(新)/ `runtime/timeline_recorder.py`(改)/ `core/lifespan.py`(改)/ `api/agents.py`(改)/ `api/tasks.py`(改)/ `api/stats.py`(改)/ `service/agent.py`(改)/ `service/metrics_cache.py`(新)/ `repository/task.py`(改)/ `repository/task_step.py`(改) |
| **PR3: Worker 中断+人机协作** | Worker INTERRUPT/PAUSE/RESUME 处理 + send_task_message 增强 + WAITING_USER 超时 + NEED_HUMAN/NEED_CONFIRM 事件流 | 中(Worker 协议) | 6 | `worker/worker_session.py`(改)/ `worker/skill/browser_skill.py`(改)/ `worker/skill/risk_heuristics.py`(新)/ `worker/stdin_listener.py`(改, RESUME payload 解析)/ `api/tasks.py`(改, send_task_message 分流)/ `service/checkpoint.py`(改, pending_ask_human 序列化) |
| **PR4: 前端适配+测试** | ChatInput 行为 + HumanResponseDialog + Timeline think 渲染 + Agent 详情 + 全部单元/集成测试 | 中(UI) | 14 | 前端 6 个组件/页面改: `ChatInput` / `HumanResponseDialog`(新)/ `Timeline` / `AgentDetailPanel` / `AgentCard` / `TaskDetailPage` + 后端 8 个测试文件: `test_react_engine.py` / `test_react_bridge.py` / `test_transitions_v25.py` / `test_cost_calculator.py` / `test_metrics_cache.py` / `test_agent_v25.py` / `test_task_messages_v25.py` / `test_v25_schemas.py` |

**预计文件合计**: 10 + 13 + 6 + 14 = **43 个**(不含 alembic 自动生成的迁移文件)。

**拆分依据**(P3-17 解释):
- **PR1 优先**: 协议层和数据层是"地基",所有上层都依赖。纯数据变更,影响面小,可以独立合并
- **PR2 跟 PR1 紧耦合但工作量大**: ReActEngine 是核心模块,集中在一个 PR 方便 review。13 个文件里 5 个新增、8 个修改
- **PR3 跟 PR2 平行**: Worker 协议独立演进,Runtime 侧 PR2 已预留好接口,Worker 侧单独 PR 避免分支冲突
- **PR4 收尾**: 前端 + 测试。前端 6 个文件改动不大但分散,测试集中一次写完

> 📌 **2026-06-11 修订**(P3-17):原 §9 "预计文件" 列只给数字(10/10/6/14),无拆分依据。补"核心文件清单" 列后,每个 PR 的工作量可验证、code review 范围可预判。

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
- YOLO 模式下**不跳过 ASK_HUMAN**(语义见 §4.6 — 能力边界无法用"全自动"绕过,否则会陷入登录死循环)
- YOLO 模式下**跳过 NEED_CONFIRM**(风险操作用户预先授权"全自动")
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
