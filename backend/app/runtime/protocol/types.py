"""协议枚举定义 —— 所有 EventType / CommandType / TaskState 等"""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    """Worker → Runtime 事件类型"""

    WORKER_READY = "WORKER_READY"  # Worker 进程启动完毕,可以接收命令
    WORKER_HEARTBEAT = "WORKER_HEARTBEAT"  # 每 30s 心跳
    STEP_START = "STEP_START"  # 开始执行一个动作
    STEP_COMPLETE = "STEP_COMPLETE"  # 一个动作执行完成
    SCREENSHOT = "SCREENSHOT"  # 截图已保存到 S3
    PROGRESS = "PROGRESS"  # 子目标进度更新
    NEED_CONFIRM = "NEED_CONFIRM"  # 高风险动作需要人工确认
    ERROR = "ERROR"  # 步骤/系统错误(任务未终止,可恢复)
    TASK_FINISHED = "TASK_FINISHED"  # 任务完成或终止(Worker 即将退出)
    TASK_STATE_CHANGED = "TASK_STATE_CHANGED"  # Runtime 内部事件:状态机发生变化
    COMMAND_ACK = "COMMAND_ACK"  # Worker 确认收到命令
    WATCHDOG_TIMEOUT = "WATCHDOG_TIMEOUT"  # Runtime 内部事件:心跳超时


class CommandType(StrEnum):
    """Runtime → Worker 命令类型

    V1 只支持四种核心命令,足够完整控制流:
    - START: 启动任务
    - CONTINUE: 人工确认后继续
    - REJECT: 人工拒绝
    - STOP: 停止任务

    V2 预留: PAUSE, RESUME, INTERRUPT, NEW_GOAL
    """

    START = "START"
    CONTINUE = "CONTINUE"
    REJECT = "REJECT"
    STOP = "STOP"


class TaskState(StrEnum):
    """Runtime 任务状态机 —— 唯一真相源"""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunMode(StrEnum):
    """任务运行模式"""

    YOLO = "yolo"  # 全自动,不需要人工确认
    SEMI = "semi"  # 半自动,高风险操作需要人工确认(V1 默认)


class TaskResult(StrEnum):
    """任务结束状态 —— Worker 通过 TASK_FINISHED 事件告知 Runtime"""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkerStatus(StrEnum):
    """Worker 自身状态 —— 通过 WORKER_HEARTBEAT 上报"""

    IDLE = "idle"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"


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
