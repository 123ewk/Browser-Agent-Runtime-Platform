"""TaskStep DTO —— 只读 DTO,没有 create/update DTO。

为什么没有 TaskStepCreate/TaskStepUpdate:
步骤由 agent 执行引擎内部写入,不通过 HTTP API 暴露给用户。
TaskStepOut 仅用于前端查看运行日志。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class TaskStepOut(BaseModel):
    """步骤出参 —— V2.5: +duration_ms/llm_latency_ms/tokens_prompt/tokens_completion/model_name/reasoning/step_type/dom_summary/visible_text"""

    id: uuid.UUID
    task_id: uuid.UUID
    step_index: int
    action: str
    result: dict | None = None
    tokens_used: int | None = None
    created_at: datetime
    duration_ms: int | None = None  # V2.5: 步骤执行耗时
    llm_latency_ms: int | None = None  # V2.5: LLM 调用延迟
    tokens_prompt: int | None = None  # V2.5: 输入 token 数
    tokens_completion: int | None = None  # V2.5: 输出 token 数
    model_name: str | None = None  # V2.5: 使用的模型名
    reasoning: str | None = None  # V2.5: ReAct 推理文本 (think 步骤)
    step_type: str = "act"  # V2.5: observe|think|act|human
    dom_summary: str | None = None  # V2.5: DOM 摘要
    visible_text: str | None = None  # V2.5: 可见文本

    model_config = {"from_attributes": True}
