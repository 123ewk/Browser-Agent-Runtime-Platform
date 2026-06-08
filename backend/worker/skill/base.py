"""Skill System 基类 —— 纯确定性执行器"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.runtime.protocol.schemas import ActionDetail


class SkillResult(BaseModel):
    """Skill 执行结果 —— 纯数据,不含决策"""

    status: Literal["ok", "error"]
    summary: str
    url: str | None = None
    title: str | None = None
    screenshot_key: str | None = None  # V1: 本地文件相对路径; V2: S3 key
    error: str | None = None


class BaseSkill(ABC):
    """能力插件基类 —— 纯确定性执行

    设计约束 (硬):
    - execute() 只执行 action,不做任何决策
    - 禁止: retry 策略 / fallback 导航 / DOM 判断 / 元素猜测
    - 失败时: 直接返回 SkillResult(status="error"),由 Worker 上报 Runtime
    """

    name: str
    description: str
    capabilities: list[str]  # e.g. ["web.navigate", "web.click", ...]

    @abstractmethod
    async def execute(self, action: ActionDetail) -> SkillResult:
        """执行单一动作,返回结果。禁止任何决策逻辑。"""
        ...


# 延迟导入避免循环依赖 —— ActionDetail 定义在 app.runtime.protocol.schemas
# 此处用 TYPE_CHECKING 做前向引用,实际类型在 worker 调用时由运行时导入解决
# 不在 import 阶段加载 schemas,避免 base.py ← schemas.py ← 其他 runtime 模块的环
