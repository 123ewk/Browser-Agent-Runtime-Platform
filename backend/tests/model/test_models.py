"""ORM 模型定义验证 —— 测试表名称、列类型、关系。"""

from __future__ import annotations

from app.model import (
    Base,
    Memory,
    PreferenceHistory,
    Task,
    User,
    UserPreference,
    UserSession,
)


def test_all_tables_in_metadata() -> None:
    """Base.metadata 包含全部 8 张业务表。"""
    tables = list(Base.metadata.tables.keys())
    assert "users" in tables
    assert "user_sessions" in tables
    assert "tasks" in tables
    assert "task_steps" in tables
    assert "checkpoints" in tables
    assert "memories" in tables
    assert "user_preferences" in tables
    assert "preference_history" in tables


def test_user_columns() -> None:
    """User 表有 username / hashed_password / created_at。"""
    cols = {c.name: c for c in User.__table__.columns}
    assert "id" in cols
    assert "username" in cols
    assert "hashed_password" in cols
    assert "created_at" in cols
    assert cols["username"].type.length == 64  # type: ignore[attr-defined]


def test_user_session_columns() -> None:
    """UserSession 表 token 为主键。"""
    cols = {c.name: c for c in UserSession.__table__.columns}
    assert cols["token"].primary_key
    assert "user_id" in cols
    assert "expires_at" in cols


def test_task_status_default() -> None:
    """Task.status 默认值为 PENDING。"""
    col = Task.__table__.columns["status"]
    # mapped_column 的 default= 是 Python 侧默认值,非 server_default
    assert col.default is not None
    assert "PENDING" in str(col.default).upper()


def test_task_result_jsonb() -> None:
    """Task.result 使用 JSONB 类型。"""
    col = Task.__table__.columns["result"]
    assert "jsonb" in str(col.type).lower()


def test_memory_embedding_dimension() -> None:
    """Memory.embedding 维度为 1024。"""
    col = Memory.__table__.columns["embedding"]
    # pgvector Vector(1024) 类型包含 dimension 信息
    assert col.type.dim == 1024  # type: ignore[attr-defined]


def test_memory_metadata_column() -> None:
    """Memory 有 metadata JSONB 列。"""
    cols = {c.name: c for c in Memory.__table__.columns}
    assert "metadata" in cols


def test_user_preference_columns() -> None:
    """UserPreference 表有 key / content / category / source / confidence 等核心列。"""
    cols = {c.name: c for c in UserPreference.__table__.columns}
    assert "user_id" in cols
    assert "key" in cols
    assert cols["key"].type.length == 128  # type: ignore[attr-defined]
    assert "content" in cols
    assert "category" in cols
    assert "source" in cols
    assert "confidence" in cols
    assert "mention_count" in cols


def test_user_preference_index_on_user_id() -> None:
    """UserPreference 在 user_id 上有索引。"""
    indexes = {i.name: i for i in UserPreference.__table__.indexes}  # type: ignore[attr-defined]
    assert "ix_user_preferences_user_id" in indexes


def test_preference_history_columns() -> None:
    """PreferenceHistory 有 preference_id FK + old_content / new_content / changed_at。"""
    cols = {c.name: c for c in PreferenceHistory.__table__.columns}
    assert "preference_id" in cols
    assert "old_content" in cols
    assert "new_content" in cols
    assert "changed_at" in cols
    # old_content nullable = NULL 表示新建
    assert cols["old_content"].nullable
    assert not cols["new_content"].nullable
