"""NEED_CONFIRM 触发白名单 —— V2.5 简单启发式, V3 替换为 ActionRiskEvaluator (ML 推理).

V2.5 用 action_type 白名单 + URL pattern 触发, 不依赖 LLM:
- 优点: 简单、可测试、无 ML 依赖
- 缺点: 粗粒度 (可能误报, 如 news.publish 会匹配 "publish")

V3 计划: ActionRiskEvaluator 基于 LLM 的风险推理, 覆盖模糊场景。
"""

from __future__ import annotations

import re

from app.runtime.protocol.schemas import ActionDetail

# action_type 级白名单 —— 高风险操作类型
_RISKY_ACTION_TYPES: set[str] = {
    "publish",  # 发布文章/评论
    "delete",  # 删除数据
    "submit_payment",  # 支付提交
    "send_email",  # 发送邮件 (可能误发)
    "update_profile",  # 修改个人信息
}

# URL 关键词白名单 (粗粒度, 作为补充)
_RISKY_URL_PATTERNS: list[str] = [
    r"/submit",
    r"/confirm",
    r"/pay",
    r"/checkout",
    r"/delete",
    r"/publish",
]


def needs_confirm(action: ActionDetail, current_url: str) -> tuple[bool, str]:
    """判断是否需要 NEED_CONFIRM

    Args:
        action: 当前准备执行的动作
        current_url: 当前页面 URL

    Returns:
        (should_confirm: bool, reason: str)
    """
    # 1. action_type 白名单
    if action.type in _RISKY_ACTION_TYPES:
        return True, f"action_type={action.type} 是高风险操作"

    # 2. URL 模式匹配
    for pattern in _RISKY_URL_PATTERNS:
        if re.search(pattern, current_url, re.IGNORECASE):
            return True, f"URL 匹配风险模式: {pattern}"

    return False, ""
