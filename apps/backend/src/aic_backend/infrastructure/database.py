"""PostgreSQL connectivity verification."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.shared import ConfigurationError


def create_database_engine(database_url: str | None) -> AsyncEngine:
    if not database_url:
        raise ConfigurationError("AIC_DATABASE_URL is required for database access")
    return create_async_engine(database_url, pool_pre_ping=True)


async def verify_database_connection(database_url: str | None) -> None:
    engine = create_database_engine(database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()
