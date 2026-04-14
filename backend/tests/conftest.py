import os
import sys

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:zxslchj12345@localhost:5432/ai_trade",
)

from app.core.config import settings

# NullPool: no persistent connections, no cross-event-loop leaks.
_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def db():
    """Returns the session factory. Tests open/close sessions in their own
    async context, so no async teardown crosses event loop boundaries."""
    return _factory
