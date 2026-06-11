"""协议枚举定义 —— 所有 EventType / CommandType / TaskState 等

V2.5 协议扩展:
- EventType: +THINK_START/THINK_COMPLETE/OBSERVE_COMPLETE/NEED_HUMAN/HUMAN_RESPONSE/INTERRUPTED/RESUMED
- CommandType: +INTERRUPT/PAUSE/RESUME (V1 已预留)
- TaskState: +WAITING_USER
- WorkerStatus: +WAITING_USER (V2.5 新增,与 WAITING_CONFIRM 区分)
- AgentStatus: 新增(与 TaskState 命名空间分离, DRAINED 替代 paused)
- ReActDecisionType: 新增 (ACT/ASK_HUMAN/DONE)
"""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    """Worker → Runtime 事件类型 (V2.5 扩展: 7 个新增)"""

    # --- V1 保留 ---
    WORKER_READY = "WORKER_READY"  # Worker 进程启动完毕,可以接收命令
    WORKER_HEARTBEAT = "WORKER_HEARTBEAT"  # 每 30s 心跳
    STEP_START = "STEP_START"  # 开始执行一个动作
    STEP_COMPLETE = "STEP_COMPLETE"  # 一个动作执行完成
    SCREENSHOT = "SCREENSHOT"  # 截图已保存到 S3
    PROGRESS = "PROGRESS"  # 子目标进度更新
    NEED_CONFIRM = "NEED_CONFIRM"  # 高风险动作需要人工确认 (V1 定义, V2.5 实现 Worker 端真实发射)
    ERROR = "ERROR"  # 步骤/系统错误(任务未终止,可恢复)
    TASK_FINISHED = "TASK_FINISHED"  # 任务完成或终止(Worker 即将退出)
    TASK_STATE_CHANGED = "TASK_STATE_CHANGED"  # Runtime 内部事件:状态机发生变化
    COMMAND_ACK = "COMMAND_ACK"  # Worker 确认收到命令
    WATCHDOG_TIMEOUT = "WATCHDOG_TIMEOUT"  # Runtime 内部事件:心跳超时

    # --- V2.5 新增 ---
    THINK_START = "THINK_START"  # ReAct 思考阶段开始 (Runtime 合成)
    THINK_COMPLETE = "THINK_COMPLETE"  # ReAct 思考完成,含 reasoning 文本 (Runtime 合成)
    OBSERVE_COMPLETE = "OBSERVE_COMPLETE"  # 页面观察完成 (Runtime 合成, 源数据来自 STEP_COMPLETE)
    NEED_HUMAN = "NEED_HUMAN"  # Agent 能力边界: 遇到登录/验证码等阻塞, 需要人类介入 (Worker 发射)
    HUMAN_RESPONSE = (
        "HUMAN_RESPONSE"  # 用户已回复 Agent (Runtime 合成, 前端通过 send_task_message 端点进入)
    )
    INTERRUPTED = "INTERRUPTED"  # Worker 已被中断 (Worker 发射)
    RESUMED = "RESUMED"  # Worker 已从中断恢复 (Worker 发射)


class CommandType(StrEnum):
    """Runtime → Worker 命令类型

    V2.5: 激活 V1 预留的 INTERRUPT / PAUSE / RESUME 三个命令。
    """

    START = "START"
    CONTINUE = "CONTINUE"
    REJECT = "REJECT"
    STOP = "STOP"
    INTERRUPT = "INTERRUPT"  # V2.5: 中断当前动作, 发 STEP_COMPLETE(aborted=true) 后转 WAITING_USER
    PAUSE = "PAUSE"  # V2.5: 完成当前 STEP_COMPLETE 后挂起主循环 (Worker 不退出)
    RESUME = "RESUME"  # V2.5: 从 PAUSED/WAITING_USER 恢复, 统一 ResumePayload 协议


class TaskState(StrEnum):
    """Runtime 任务状态机 —— 唯一真相源 (V2.5: +WAITING_USER)"""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"  # 风险确认等待
    WAITING_USER = "waiting_user"  # V2.5 新增: 等待人类输入 (Agent 求助 或 用户中断)
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunMode(StrEnum):
    """任务运行模式"""

    YOLO = "yolo"  # 全自动, 跳过 NEED_CONFIRM (但不跳过 NEED_HUMAN——能力边界无法用"全自动"绕过)
    SEMI = "semi"  # 半自动, 高风险操作需要人工确认 (V1 默认)


class TaskResult(StrEnum):
    """任务结束状态 —— Worker 通过 TASK_FINISHED 事件告知 Runtime"""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkerStatus(StrEnum):
    """Worker 自身状态 —— 通过 WORKER_HEARTBEAT 上报 (V2.5: +WAITING_USER)"""

    IDLE = "idle"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"  # V1: 等用户对 NEED_CONFIRM 响应
    WAITING_USER = "waiting_user"  # V2.5 新增: 等用户对 NEED_HUMAN/INTERRUPT/PAUSE 响应


class AgentStatus(StrEnum):
    """Agent 整体状态 (V2.5 新增, 与 TaskState 命名空间分离)

    与 TaskState.PAUSED 的区别:
    - TaskState.PAUSED = 单个任务的暂停 (用户操作)
    - AgentStatus.DRAINED = Agent 整体停止接收新任务 (运维操作)
    """

    ACTIVE = "active"  # 正常运行
    DRAINED = "drained"  # V2.5: 停止接收新任务 (Kubernetes 术语, 与 TaskState.PAUSED 区分)
    DEPRECATED = "deprecated"  # 永久下线


class ReActDecisionType(StrEnum):
    """ReAct 决策输出类型 (V2.5 新增)"""

    ACT = "ACT"  # 执行下一步浏览器动作
    ASK_HUMAN = "ASK_HUMAN"  # 阻塞, 需要人类介入 (登录/验证码等)
    DONE = "DONE"  # 目标已达成


class ConfirmSeverity(StrEnum):
    """NEED_CONFIRM 事件的严重等级"""

    LOW = "low"  # 低风险:常规但不可逆操作
    MEDIUM = "medium"  # 中风险:涉及数据修改
    HIGH = "high"  # 高风险:涉及发布/删除/支付


class RiskLevel(StrEnum):
    """Action 风险等级 —— ActionRiskEvaluator 输出"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FailureType(StrEnum):
    """任务失败类型 —— ERROR 事件的 error_type 字段"""

    SYSTEM_ERROR = "SYSTEM_ERROR"  # 系统级错误(进程崩溃/内存不足)
    BROWSER_ERROR = "BROWSER_ERROR"  # 浏览器错误(页面崩溃/JS异常)
    TIMEOUT = "TIMEOUT"  # 超时(步骤超时/任务超时)
    USER_CANCELLED = "USER_CANCELLED"  # 用户主动取消
    MAX_STEPS_EXCEEDED = "MAX_STEPS_EXCEEDED"  # 超过最大步数
    GOAL_FAILED = "GOAL_FAILED"  # 目标判定失败(GoalChecker 判定不可完成)
