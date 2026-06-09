"""UserPreferenceRepository —— 用户偏好 CRUD + 变更审计。

设计要点:
- list_by_user: 全量加载,注入 system prompt
- upsert: user_id + key 唯一,重复则更新 → 记录 preference_history
- delete: 级联删除 preference_history (DB 层 ondelete CASCADE)
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.preference_history import PreferenceHistory
from app.model.user_preference import UserPreference
from app.schema.user_preference import PreferenceCreate, PreferenceOut


class UserPreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_user(self, user_id: uuid.UUID) -> list[PreferenceOut]:
        """全量加载当前用户的所有偏好,按 key 排序保证 stable order"""
        stmt = (
            select(UserPreference)
            .where(UserPreference.user_id == user_id)
            .order_by(UserPreference.key)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [PreferenceOut.model_validate(r) for r in rows]

    async def upsert(self, user_id: uuid.UUID, dto: PreferenceCreate) -> PreferenceOut:
        """按 (user_id, key) 唯一约束 upsert, 记录变更历史"""
        stmt = select(UserPreference).where(
            UserPreference.user_id == user_id,
            UserPreference.key == dto.key,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()

        if row is not None:
            old_content = row.content
            row.content = dto.content
            row.category = dto.category
            row.source = dto.source
            row.mention_count = row.mention_count + 1
        else:
            old_content = None
            row = UserPreference(
                user_id=user_id,
                key=dto.key,
                content=dto.content,
                category=dto.category,
                source=dto.source,
            )
            self._session.add(row)

        await self._session.flush()

        # 写审计日志
        history = PreferenceHistory(
            preference_id=row.id,
            old_content=old_content,
            new_content=dto.content,
        )
        self._session.add(history)

        return PreferenceOut.model_validate(row)

    async def delete(self, pref_id: uuid.UUID) -> bool:
        """删除偏好, preference_history 由 DB 层 ondelete CASCADE 自动清理"""
        row = await self._session.get(UserPreference, pref_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    async def get_by_id(self, pref_id: uuid.UUID) -> PreferenceOut | None:
        row = await self._session.get(UserPreference, pref_id)
        return PreferenceOut.model_validate(row) if row else None
