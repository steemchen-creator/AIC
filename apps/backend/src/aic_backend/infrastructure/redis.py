"""Redis connectivity verification."""

from typing import cast

from redis.asyncio import Redis

from aic_backend.shared import ConfigurationError


def create_redis_client(redis_url: str | None) -> Redis:
    if not redis_url:
        raise ConfigurationError("AIC_REDIS_URL is required for Redis access")
    return cast(Redis, Redis.from_url(redis_url, decode_responses=True))


async def verify_redis_connection(redis_url: str | None) -> None:
    client = create_redis_client(redis_url)
    try:
        await client.ping()
    finally:
        await client.aclose()
