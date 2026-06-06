"""UserRepository 单元测试 —— Mock AsyncSession 验证 CRUD 行为。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.model import User
from app.repository.user import UserRepository


@pytest.fixture
def mock_session() -> AsyncMock:
    """构造一个假 AsyncSession,提供 add / flush / execute / get。"""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.get = AsyncMock()
    return session


@pytest.fixture
def repo(mock_session: AsyncMock) -> UserRepository:
    return UserRepository(mock_session)


def _make_user(username: str = "alice", hashed_password: str = "hashed_xxx") -> User:
    """构造一个带完整字段的 User ORM 对象,模拟 flush 后的状态。"""
    return User(
        id=uuid.uuid4(),
        username=username,
        hashed_password=hashed_password,
        created_at=datetime.now(UTC),
    )


async def test_create_returns_user_out(repo: UserRepository) -> None:
    """create 应返回 UserOut(含 id / username)。"""
    result = await repo.create("alice", "hashed_xxx")
    assert result.username == "alice"
    assert isinstance(result.id, uuid.UUID)


async def test_get_by_username_found(repo: UserRepository) -> None:
    """用户名存在时返回 UserOut。"""
    # 模拟 select 返回的 scalar_result
    mock_result = MagicMock()
    mock_user = MagicMock()
    mock_user.username = "bob"
    mock_user.hashed_password = "xxx"
    mock_user.id = uuid.uuid4()
    mock_user.created_at = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_user)
    repo._session.execute = AsyncMock(return_value=mock_result)  # type: ignore[method-assign]

    result = await repo.get_by_username("bob")
    assert result is not None
    assert result.username == "bob"


async def test_get_by_username_not_found(repo: UserRepository) -> None:
    """用户名不存在时返回 None。"""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    repo._session.execute = AsyncMock(return_value=mock_result)  # type: ignore[method-assign]

    result = await repo.get_by_username("nobody")
    assert result is None


async def test_verify_credentials_success(repo: UserRepository) -> None:
    """正确密码应返回 UserOut。"""
    from bcrypt import gensalt, hashpw

    hashed = hashpw(b"secret123", gensalt()).decode()
    mock_user = MagicMock()
    mock_user.username = "carol"
    mock_user.hashed_password = hashed
    mock_user.id = uuid.uuid4()
    mock_user.created_at = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_user)
    repo._session.execute = AsyncMock(return_value=mock_result)  # type: ignore[method-assign]

    result = await repo.verify_credentials("carol", "secret123")
    assert result is not None
    assert result.username == "carol"


async def test_verify_credentials_wrong_password(repo: UserRepository) -> None:
    """错误密码应返回 None。"""
    from bcrypt import gensalt, hashpw

    hashed = hashpw(b"correct", gensalt()).decode()
    mock_user = MagicMock()
    mock_user.hashed_password = hashed
    mock_user.username = "dave"
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_user)
    repo._session.execute = AsyncMock(return_value=mock_result)  # type: ignore[method-assign]

    result = await repo.verify_credentials("dave", "wrong")
    assert result is None
