"""Operational dependency verification."""

from aic_backend.infrastructure.database import verify_database_connection
from aic_backend.infrastructure.redis import verify_redis_connection
from aic_backend.shared import Settings


async def verify_dependencies(settings: Settings) -> None:
    await verify_database_connection(settings.database_url)
    await verify_redis_connection(settings.redis_url)
