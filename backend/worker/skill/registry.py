"""Skill Registry —— Worker 端唯一技能注册中心

设计约束 (硬):
- 只在 Worker 存在, Runtime 不持有 SkillRegistry
- Runtime 只输出 skill_name, Worker 负责查找和执行
"""

from __future__ import annotations

from .base import BaseSkill


class SkillNotFoundError(KeyError):
    """请求的 Skill 未注册"""

    def __init__(self, name: str) -> None:
        super().__init__(f"Skill 未注册: {name}")
        self.skill_name = name


class SkillRegistry:
    """Worker 端技能注册中心

    用法:
        registry = SkillRegistry()
        registry.register(BrowserSkill())
        skill = registry.get("browser")
    """

    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        """注册一个技能"""
        self._skills[skill.name] = skill

    def get(self, name: str) -> BaseSkill:
        """按名称获取技能

        Raises:
            SkillNotFoundError: 技能未注册
        """
        if name not in self._skills:
            raise SkillNotFoundError(name)
        return self._skills[name]

    def find_by_capability(self, capability: str) -> list[BaseSkill]:
        """按能力标签查找技能 (V2: capability-based routing)"""
        return [s for s in self._skills.values() if capability in s.capabilities]

    def list_all(self) -> list[BaseSkill]:
        """列出所有已注册技能"""
        return list(self._skills.values())
