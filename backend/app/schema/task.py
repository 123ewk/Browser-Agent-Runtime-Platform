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
    """创建 DTO —— 用户只需要描述目标,user_id 从当前登录用户获取。"""

    goal: str = Field(min_length=1, max_length=2000)


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
    goal: str
    status: str
    result: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
