"""Backend configuration."""

from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIC_", case_sensitive=False, extra="ignore")
    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    database_url: str | None = None
    redis_url: str | None = None
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    verify_dependencies: bool = False
    tushare_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
