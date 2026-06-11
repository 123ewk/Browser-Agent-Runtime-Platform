"""ORM 模型层 —— 禁止反向依赖:api → service → repository → model。

所有模型在此集中导出,便于 Alembic 和 repository 层统一引用:
  from app.model import Base, User, Task, ...

pgvector 扩展通过 Memory.embedding(Vector(1024)) 使用,迁移中手动创建。
"""

from app.model.agent import Agent
from app.model.base import Base, UUIDMixin
from app.model.checkpoint import Checkpoint
from app.model.memory import Memory
from app.model.preference_history import PreferenceHistory
from app.model.session import UserSession
from app.model.task import Task
from app.model.task_step import TaskStep
from app.model.user import User
from app.model.user_preference import UserPreference

__all__ = [
    "Base",
    "UUIDMixin",
    "Agent",
    "User",
    "UserSession",
    "Task",
    "TaskStep",
    "Checkpoint",
    "Memory",
    "UserPreference",
    "PreferenceHistory",
]
