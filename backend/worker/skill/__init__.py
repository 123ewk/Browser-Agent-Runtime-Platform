"""Skill System —— Worker 端可插拔能力注册

设计约束 (硬):
- BaseSkill = 纯确定性执行器, 零决策逻辑
- 禁止: retry, fallback, DOM 判断, 条件分支
- 只做: 接收 ActionDetail → 执行 → 返回 SkillResult
"""

from worker.skill.base import BaseSkill, SkillResult
from worker.skill.browser_skill import BrowserSkill
from worker.skill.registry import SkillNotFoundError, SkillRegistry

__all__ = [
    "BaseSkill",
    "BrowserSkill",
    "SkillNotFoundError",
    "SkillRegistry",
    "SkillResult",
]
