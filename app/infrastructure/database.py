from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(get_settings().database_url, echo=False)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session

# NOTE: schema creation lives in Alembic (`alembic upgrade head`), not here.
# `create_all` used to run on startup; it cannot alter an existing table, so the
# first schema change against real data had no safe path — and concurrent
# uvicorn workers raced on CREATE TABLE, which is why the Dockerfile ran one.
