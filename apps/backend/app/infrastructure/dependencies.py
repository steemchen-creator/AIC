from apps.backend.app.infrastructure.database import verify_database_connection
from apps.backend.app.infrastructure.redis import verify_redis_connection
from core.config import Settings


async def verify_dependencies(settings: Settings) -> None:
    await verify_database_connection(settings.database_url)
    await verify_redis_connection(settings.redis_url)
