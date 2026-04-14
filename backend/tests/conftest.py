import os
import sys

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:zxslchj12345@localhost:5432/ai_trade",
)

from app.core.config import settings


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    eng = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=3)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(scope="session")
async def session_factory(test_engine):
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s
