"""协议消息模型 —— RuntimeEvent / Command + 所有 Payload

设计要点:
- 全部用 Pydantic BaseModel,支持 .model_dump_json() 序列化为 JSON Lines
- payload 用 Field(default_factory=dict) 避免 mutable default 陷阱
- 事件和命令的 id 字段用于请求-响应追踪(event_id / command_id)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .constants import PROTOCOL_VERSION
from .types import (
    CommandType,
    ConfirmSeverity,
    EventType,
    RiskLevel,
    RunMode,
    TaskResult,
    WorkerStatus,
)

# ═══════════════════════════════════════════════════════════════
# 核心消息
# ═══════════════════════════════════════════════════════════════


class RuntimeEvent(BaseModel):
    """Worker → Runtime | EventBus 内流通的统一事件格式

    每条事件嵌入 version + event_id + ts,保证可追踪可重放。
    """

    version: str = PROTOCOL_VERSION
    event_id: str
    event: EventType
    ts: datetime
    task_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class Command(BaseModel):
    """Runtime → Worker 统一命令格式"""

    command_id: str
    type: CommandType
    payload: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# 事件 Payload
# ═══════════════════════════════════════════════════════════════


class StepStartPayload(BaseModel):
    """STEP_START 事件的 payload"""

    index: int  # 步骤序号(从 1 开始)
    action: str  # "navigate" | "click" | "input_text" | "scroll" | "extract" | ...
    description: str  # 人类可读的动作描述
    reasoning: str = ""  # LLM 决策推理


class StepCompletePayload(BaseModel):
    """STEP_COMPLETE 事件的 payload (V2.5 扩展: +dom_summary/visible_text/step_type/reasoning/aborted/abort_reason)"""

    index: int
    action: str
    summary: str  # 执行结果摘要
    url: str | None = None  # 执行后所在页面 URL
    title: str | None = None  # 页面标题 (Trajectory 回传)
    duration_ms: int | None = None  # 执行耗时(毫秒), V2.0 已定义 V2.5 真正填充
    is_terminal: bool = False  # Worker 报告 local terminal signal
    dom_summary: str = ""  # V2.5: Worker 导航类动作后提取的 DOM 摘要 (结构化可交互元素, ≤3000 字符)
    visible_text: str = ""  # V2.5: Worker 导航类动作后提取的可见文本 (≤2000 字符)
    step_type: str = "act"  # V2.5: observe|think|act|human
    reasoning: str = ""  # V2.5: think 步骤的推理文本
    aborted: bool = False  # V2.5: True = 步骤被 INTERRUPT 强制中止
    abort_reason: str = ""  # V2.5: user_interrupt | agent_ask_human | system


class ScreenshotPayload(BaseModel):
    """SCREENSHOT 事件的 payload —— 截图已保存

    V1 保存到本地文件系统,V2 升级为 S3。
    file_key 是截图的相对路径,前端通过 /screenshots/{file_key} 获取。
    """

    file_key: str  # 截图相对路径,如 "screenshots/abc123.png"


class ProgressPayload(BaseModel):
    """PROGRESS 事件的 payload —— 子目标进度"""

    current: int  # 当前步骤
    total: int  # 总步骤(可能随执行动态调整)
    message: str = ""  # 进度描述


class NeedConfirmPayload(BaseModel):
    """NEED_CONFIRM 事件的 payload —— 需要人工确认"""

    action_tag: str  # "publish_video" | "delete_resource" | "submit_form" | ...
    question: str  # 显示给用户看的问题(中文)
    severity: ConfirmSeverity = ConfirmSeverity.MEDIUM
    context: dict[str, Any] = Field(default_factory=dict)  # 辅助上下文(如当前 URL)


class ErrorPayload(BaseModel):
    """ERROR 事件的 payload —— 步骤/系统错误"""

    error_type: str  # FailureType 值或自定义字符串
    message: str  # 人类可读的错误描述
    retryable: bool = False  # 是否可重试
    step_index: int | None = None  # 出错时所在的步骤序号
    details: dict[str, Any] = Field(default_factory=dict)  # 额外调试信息


class TaskFinishedPayload(BaseModel):
    """TASK_FINISHED 事件的 payload —— Worker 任务结束"""

    status: TaskResult
    summary: str  # 任务完成/失败的人类可读摘要
    total_steps: int = 0  # 总共执行的步骤数


class HeartbeatPayload(BaseModel):
    """WORKER_HEARTBEAT 事件的 payload"""

    seq: int  # 心跳序号(单调递增)
    status: WorkerStatus = WorkerStatus.RUNNING


class CommandAckPayload(BaseModel):
    """COMMAND_ACK 事件的 payload —— Worker 确认收到命令"""

    command_id: str  # 确认收到的命令 ID
    accepted: bool = True
    message: str = ""


class TaskStateChangedPayload(BaseModel):
    """TASK_STATE_CHANGED 事件的 payload —— Runtime 内部状态变更"""

    from_state: str
    to_state: str
    reason: str = ""


class WatchdogTimeoutPayload(BaseModel):
    """WATCHDOG_TIMEOUT 事件的 payload —— 心跳超时

    携带超时任务的完整上下文,供消费方(EventBus subscriber)做出正确决策:
    - task_id / worker_pid: 确定是哪个 Worker 超时
    - last_heartbeat_seq / seconds_since_last: 超时严重程度
    - status_at_last: 超时前 Worker 状态("是否正在执行关键操作")
    """

    last_heartbeat_seq: int
    seconds_since_last: float
    task_id: str  # 超时的任务 ID(必填,由 _fire_timeout 显式传入)
    worker_pid: int | None = None
    status_at_last: str  # 超时前 Worker 状态(必填,如 "running"/"idle")


# ═══════════════════════════════════════════════════════════════
# 命令 Payload
# ═══════════════════════════════════════════════════════════════


class StartPayload(BaseModel):
    """START 命令的 payload —— 启动任务"""

    session_id: str  # 会话 ID(用于日志关联)
    goal: str  # 任务目标(自然语言)
    skill: str = "browser"  # PolicyEngine 选择的技能名
    action: ActionDetail | None = None  # PolicyEngine 输出的动作 (第一步)
    storage_state_path: str | None = None  # 浏览器登录态路径(复用已有会话)
    run_mode: RunMode = RunMode.SEMI
    max_steps: int = 20
    timeout_seconds: int = 120


class ContinuePayload(BaseModel):
    """CONTINUE 命令的 payload —— 人工确认后继续 / Auto Loop 下一步动作"""

    approved: bool = True
    feedback: str = ""  # 用户的额外反馈(可选)
    action: dict | None = None  # Auto Loop: PolicyEngine 输出的下一步动作


class RejectPayload(BaseModel):
    """REJECT 命令的 payload —— 人工拒绝某操作"""

    reason: str  # 拒绝原因


class StopPayload(BaseModel):
    """STOP 命令的 payload —— 停止任务"""

    reason: str = "user_requested"  # "user_requested" | "timeout" | "error"


# ═══════════════════════════════════════════════════════════════
# V2.5 新增 Payload
# ═══════════════════════════════════════════════════════════════


class ThinkCompletePayload(BaseModel):
    """THINK_COMPLETE 事件的 payload (Runtime 合成)"""

    step_index: int
    reasoning: str  # 完整推理文本 (Timeline 展示用)
    decision: str  # "ACT" | "ASK_HUMAN" | "DONE"
    confidence: float = 1.0
    tokens_used: int = 0  # 本次 LLM 调用消耗的 token
    llm_latency_ms: int = 0  # LLM 调用延迟


class NeedHumanPayload(BaseModel):
    """NEED_HUMAN 事件的 payload (Worker 发射, BrowserSkill 检测到阻塞)"""

    block_type: str  # login | captcha | paywall | consent | other
    question: str  # 问用户的问题
    context_url: str | None = None
    screenshot_key: str | None = None  # S3 key, 前端展示截图


class ObserveCompletePayload(BaseModel):
    """OBSERVE_COMPLETE 事件的 payload (Runtime 合成, 源数据来自 STEP_COMPLETE)"""

    step_index: int
    url: str | None = None
    title: str | None = None
    dom_summary: str = ""  # 压缩后的 DOM 文本 (Worker 上报, Runtime 转发)
    visible_text: str = ""  # 页面可见文本 (前 2000 字符, Worker 上报, Runtime 转发)


class InterruptPayload(BaseModel):
    """INTERRUPT 命令的 payload (Runtime → Worker)"""

    reason: str  # "user_interrupt" | "agent_ask_human" | "system"
    user_message: str = ""  # 用户说的内容 (用户主动中断时填)
    ask_human_block_type: str = ""  # Agent 求助时的 block_type
    ask_human_question: str = ""  # Agent 求助时的 question


class ResumePayload(BaseModel):
    """RESUME 命令的统一 payload (Runtime → Worker)

    无论来自 PAUSE 还是 INTERRUPT, Worker 都按此解析。
    Worker 不区分来源, 只把 payload 透传给 Runtime。
    """

    feedback: str = ""  # 用户反馈 (空=纯恢复, 非空=用户补充指令)
    ask_human_block_type: str = ""  # 透传: Agent 求助时的 block_type
    ask_human_question: str = ""  # 透传: Agent 求助时的 question
    previous_interrupt_reason: str = ""  # 透传: 上一次 INTERRUPT 的 reason


class PausePayload(BaseModel):
    """PAUSE 命令的 payload (Runtime → Worker)"""

    reason: str = "user_requested"  # user_requested | maintenance | system


class StepAbortedPayload(BaseModel):
    """步骤中止的上下文 —— 供 TimelineRecorder 写入 task_steps"""

    step_index: int
    aborted: bool = True
    abort_reason: str = ""  # user_interrupt | agent_ask_human | system


# ═══════════════════════════════════════════════════════════════
# Worker 内部模型(不在 stdin/stdout 协议中,供 Worker 模块使用)
# ═══════════════════════════════════════════════════════════════


class ActionDetail(BaseModel):
    """PolicyEngine 输出的单一动作 —— 极简,只含执行所需字段

    与 Action(旧)的区别:
    - Action 含 reasoning/confidence/risk_level,是 V2 ActionPlanner 的内部模型
    - ActionDetail 只含 type/target/value/description,是协议层传输模型
    """

    type: str  # navigate | click | input_text | screenshot | extract
    target: str | None = None  # URL / CSS selector
    value: str | None = None  # 输入值
    description: str = ""


class DecisionResponse(BaseModel):
    """决策引擎输出 (V2.5 扩展: +decision_type/confidence/tokens_used/model_used/llm_latency_ms)"""

    skill: str  # "browser"
    action: ActionDetail
    reasoning: str = ""  # LLM 决策理由 (debug 用)
    is_terminal: bool = False  # Policy 建议终止 (Runtime 最终判定)
    decision_type: str = "ACT"  # V2.5: ACT|ASK_HUMAN|DONE (ReActDecisionType)
    confidence: float = 1.0  # V2.5: LLM 置信度
    tokens_used: int = 0  # V2.5: 本次调用消耗的 token
    model_used: str = ""  # V2.5: 使用的模型名
    llm_latency_ms: int = 0  # V2.5: LLM 调用延迟


class ExecutionContract(BaseModel):
    """执行边界 —— Worker 在一个 goal 内的约束

    由 Runtime 通过 START 命令下发,Worker 在每次循环时检查边界。
    """

    goal: str
    max_steps: int = 20
    timeout_seconds: int = 120


class Action(BaseModel):
    """统一动作表示 —— ActionPlanner 输出,ActionExecutor 执行 (V2)"""

    type: str  # "navigate" | "click" | "input_text" | "scroll" | "extract" | "wait"
    target_selector: str | None = None  # CSS selector / text / role
    value: str | None = None  # 输入值(对 input_text) 或 URL(对 navigate)
    description: str  # 人类可读的动作描述
    reasoning: str  # LLM 决策推理
    confidence: float = 1.0  # LLM 置信度(0-1)
    risk_level: RiskLevel = RiskLevel.LOW  # ActionRiskEvaluator 评估后填充


class RecoveryContext(BaseModel):
    """恢复上下文 —— 出错时 ActionExecutor 构建,交给 Recovery Decision Function"""

    failed_action: Action  # 导致失败的动作
    failed_attempts: int  # 该动作已重试次数
    selectors_tried: list[str] = Field(default_factory=list)  # 已尝试的选择器
    visited_urls: list[str] = Field(default_factory=list)  # 已访问的 URL(回退用)
    last_successful_step: int = 0  # 最后一个成功的步骤序号
    error_message: str = ""
