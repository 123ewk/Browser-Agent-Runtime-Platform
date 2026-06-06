"""MemoryRepository —— 占位,Phase 2+ 实现。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class MemoryRepository:
    """记忆数据访问 —— 只建表,方法 Phase 2+ 实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
