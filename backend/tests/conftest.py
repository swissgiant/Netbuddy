import asyncio
from collections.abc import AsyncIterator

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import netbuddy.db.models  # noqa: F401 -- registers all tables on Base.metadata
from netbuddy.core.config import get_settings
from netbuddy.db.base import Base

TEST_DB_NAME = "netbuddy_test"


def _test_database_url() -> str:
    base = get_settings().database_url
    return base.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"


async def _ensure_test_database() -> None:
    admin_url = (
        get_settings()
        .database_url.replace("postgresql+asyncpg", "postgresql")
        .rsplit("/", 1)[0]
        + "/postgres"
    )
    conn = await asyncpg.connect(admin_url)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def test_database_ready() -> None:
    asyncio.run(_ensure_test_database())


@pytest.fixture
async def db_session(test_database_ready: None) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(_test_database_url(), future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()
