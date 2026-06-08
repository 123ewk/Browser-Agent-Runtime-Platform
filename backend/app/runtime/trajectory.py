"""Trajectory —— 累积态操作轨迹, PolicyEngine 的决策输入

设计约束 (硬):
- append-only: 只追加不覆盖
- 窗口限制: deque(maxlen=20), 自动丢弃最旧记录
- PolicyEngine 接收完整轨迹,不是只接收 last step
- Worker 构建, Runtime 透传, PolicyEngine 消费
"""

from __future__ import annotations

from collections import deque

from pydantic import BaseModel, PrivateAttr

from app.runtime.protocol.schemas import ActionDetail


class StepRecord(BaseModel):
    """单步轨迹记录 —— append-only"""

    step_index: int
    action_type: str
    action_description: str
    result_summary: str
    url: str | None = None
    title: str | None = None
    error: str | None = None


class Trajectory(BaseModel):
    """累积态操作轨迹

    窗口限制: _history 使用 deque(maxlen=20), 超出自动丢弃最旧记录。
    V2 升级为 TrajectorySummarizer 压缩历史为摘要。

    Worker 构建 → STEP_COMPLETE payload → Runtime 透传 → PolicyEngine 消费
    """

    model_config = {"arbitrary_types_allowed": True}

    url: str | None = None
    title: str | None = None
    step_index: int = 0
    error: str | None = None

    _history: deque[StepRecord] = PrivateAttr(default_factory=lambda: deque(maxlen=20))

    @property
    def history(self) -> list[StepRecord]:
        """返回历史记录列表 (PolicyEngine 消费)"""
        return list(self._history)

    @property
    def is_empty(self) -> bool:
        return len(self._history) == 0

    def add_step(
        self,
        action: ActionDetail,
        url: str | None = None,
        title: str | None = None,
        summary: str = "",
        error: str | None = None,
    ) -> None:
        """追加步骤,自动遵守窗口限制"""
        record = StepRecord(
            step_index=self.step_index + 1,
            action_type=action.type,
            action_description=action.description,
            result_summary=summary,
            url=url,
            title=title,
            error=error,
        )
        self._history.append(record)
        self.step_index = record.step_index
        self.url = url
        self.title = title
        self.error = error

    def summary_for_prompt(self) -> str:
        """生成给 PolicyEngine prompt 用的轨迹摘要"""
        if not self._history:
            return "(empty - first step, no actions executed yet)"

        lines = []
        for r in self._history:
            status = "[ERR]" if r.error else "[OK]"
            lines.append(
                f"  {status} Step {r.step_index}: {r.action_type} - "
                f"{r.action_description} -> {r.result_summary[:80]}"
            )
            if r.url:
                lines.append(f"       URL: {r.url}")
            if r.title:
                lines.append(f"       Title: {r.title}")
        return "\n".join(lines)
