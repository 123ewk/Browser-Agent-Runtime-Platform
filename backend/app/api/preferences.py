"""偏好 API —— 用户长期记忆的 CRUD + /remember LLM 压缩入口

端点:
  GET  /preferences           — 全量返回用户偏好(system prompt 数据源)
  POST /preferences           — 创建/更新偏好(upsert on key)
  POST /preferences/remember  — /remember 指令: 自然语言 → LLM 压缩 → 写入
  DELETE /preferences/{id}    — 删除偏好
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import UUID4

from app.core.deps import get_current_user_id
from app.infra.llm import ChatLLM
from app.infra.postgres import PostgresClient
from app.repository.user_preference import UserPreferenceRepository
from app.schema.user_preference import (
    PreferenceCreate,
    PreferenceOut,
    RememberRequest,
    RememberResponse,
)
from app.service.preference_extractor import PreferenceExtractor

router = APIRouter(prefix="/preferences", tags=["preferences"])
log = structlog.get_logger(__name__)

# ── 全局单例(V1 模式, 与 tasks.py 一致) ──
_extractor: PreferenceExtractor | None = None


def init_preference_extractor(llm: ChatLLM) -> None:
    """初始化 PreferenceExtractor —— 在 FastAPI startup 后调用"""
    global _extractor
    _extractor = PreferenceExtractor(llm)
    log.info("preference_extractor.initialized")


def _get_pg() -> PostgresClient:
    """获取 pg client(V1 全局引用)"""
    from app.api.tasks import _pg_client

    if _pg_client is None:
        raise HTTPException(503, "Database not available")
    return _pg_client


# ═══════════════════════════════════════════════════════════════
# REST 端点
# ═══════════════════════════════════════════════════════════════


@router.get("")
async def list_preferences(
    user_id: UUID4 = Depends(get_current_user_id),
) -> list[PreferenceOut]:
    """全量返回当前用户的偏好,用于 system prompt 构造"""
    pg = _get_pg()
    session = pg.session()
    try:
        repo = UserPreferenceRepository(session)
        return await repo.list_by_user(user_id)
    except Exception:
        await session.rollback()
        log.warning("preferences.list_failed", exc_info=True)
        raise HTTPException(500, "Failed to load preferences") from None
    finally:
        await session.close()


@router.post("", status_code=201)
async def create_preference(
    payload: PreferenceCreate,
    user_id: UUID4 = Depends(get_current_user_id),
) -> PreferenceOut:
    """创建/更新偏好(upsert on user_id + key)"""
    pg = _get_pg()
    session = pg.session()
    try:
        repo = UserPreferenceRepository(session)
        result = await repo.upsert(user_id, payload)
        await session.commit()
        log.info("preference.saved", user_id=str(user_id), key=payload.key)
        return result
    except Exception:
        await session.rollback()
        log.warning("preferences.create_failed", exc_info=True)
        raise HTTPException(500, "Failed to save preference") from None
    finally:
        await session.close()


@router.delete("/{pref_id}", status_code=204)
async def delete_preference(
    pref_id: UUID4,
    user_id: UUID4 = Depends(get_current_user_id),
) -> None:
    """删除偏好"""
    pg = _get_pg()
    session = pg.session()
    try:
        repo = UserPreferenceRepository(session)
        deleted = await repo.delete(pref_id)
        if not deleted:
            raise HTTPException(404, "Preference not found")
        await session.commit()
    except HTTPException:
        raise
    except Exception:
        await session.rollback()
        log.warning("preferences.delete_failed", exc_info=True)
        raise HTTPException(500, "Failed to delete preference") from None
    finally:
        await session.close()


@router.post("/remember")
async def remember(
    payload: RememberRequest,
    user_id: UUID4 = Depends(get_current_user_id),
) -> RememberResponse:
    """用户说"记住:xxx", LLM 压缩提取后写入偏好"""
    if _extractor is None:
        raise HTTPException(503, "Preference extractor not available")

    # LLM 压缩
    extracted = await _extractor.extract(payload.content)
    if not extracted:
        return RememberResponse(extracted=[])

    # 逐条写入
    pg = _get_pg()
    session = pg.session()
    results: list[PreferenceOut] = []
    try:
        repo = UserPreferenceRepository(session)
        for item in extracted:
            dto = PreferenceCreate(
                key=item["key"],
                content=item["content"],
                category=item.get("category", "PREFERENCE"),
                source="EXPLICIT",
            )
            result = await repo.upsert(user_id, dto)
            results.append(result)
        await session.commit()
        log.info(
            "remember.saved",
            user_id=str(user_id),
            count=len(results),
        )
    except Exception:
        await session.rollback()
        log.warning("remember.save_failed", exc_info=True)
        raise HTTPException(500, "Failed to save extracted preferences") from None
    finally:
        await session.close()

    return RememberResponse(extracted=results)
