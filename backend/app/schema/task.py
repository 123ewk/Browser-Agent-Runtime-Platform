"""Task DTO —— TaskUpdate 只暴露 status+result 两个可写字段。

为什么 TaskUpdate 只有 status 和 result,不允许改 goal:
- goal 是用户的任务目标,一旦创建就不应该被修改,否则审计追踪会混乱
- 只有 agent 执行引擎需要更新 status(状态流转)和 result(执行结果)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    """创建 DTO —— 用户描述目标,可选指定 agent。"""

    goal: str = Field(min_length=1, max_length=2000)
    agent_id: uuid.UUID | None = None  # V2 新增,不传则用 default agent


class TaskUpdate(BaseModel):
    """更新 DTO —— 所有字段可选,只传需要改的字段。

    为什么全都 Optional: TaskUpdate 同时承担"状态推进"和"结果写入"
    两个职责,而 agent 执行时往往只更新 status(如 RUNNING→COMPLETED),
    不一定同时有 result。
    """

    status: str | None = None
    result: dict | None = None


class TaskOut(BaseModel):
    """任务出参 —— result 为 None 表示任务尚未完成。"""

    id: uuid.UUID
    user_id: uuid.UUID
    agent_id: uuid.UUID | None = None  # V2 新增,历史任务可能为 NULL(迁移前)
    goal: str
    status: str
    result: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskMessageCreate(BaseModel):
    """用户向 Agent 发送指令 —— 半自动模式确认/拒绝/反馈

    content: 用户输入的指令文本(如"继续"/"取消"/"换一种方式")
    run_mode: 当前运行模式(yolo=全自动, semi=半自动)
    """

    content: str = Field(min_length=1, max_length=2000)
    run_mode: str = Field(default="semi", pattern=r"^(yolo|semi)$")


class TaskMessageOut(BaseModel):
    """消息出参 —— 与前端 ChatMessage 类型对齐"""

    id: str
    task_id: str
    role: str  # "user" | "agent"
    content: str
    created_at: str  # ISO 8601


class TaskListResponse(BaseModel):
    """分页响应 —— 用 limit/offset 而非 cursor 分页。

    为什么不用 cursor 分页: 任务列表按 updated_at 降序,
    翻页时用户期望看到"第 2 页"这种确定位置,而不是"加载更多"。
    offset 分页更适合这种场景。
    """

    items: list[TaskOut]
    total: int
    limit: int
    offset: int


class TaskActionResponse(BaseModel):
    """通用任务动作响应 —— 用于 stop / pause / resume 接口的出参

    字段含义:
    - task_id:  任务 ID
    - state:    转换后的状态(不一定等于目标状态,如对终态任务调 stop 会返回原状态)
    - accepted: 请求是否被接受(状态转换是否成功)
    - reason:   失败时的原因(成功时为空字符串)

    为什么用通用响应而非各自一个 DTO:
    - 三个接口的响应语义相似(请求 → 状态变更)
    - 通用 DTO 减少 schema 维护成本,前端用一个 type 就能接
    """

    task_id: str
    state: str
    accepted: bool
    reason: str = ""
