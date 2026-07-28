from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from apps.backend.app.infrastructure.dependencies import verify_dependencies
from core.config import get_settings
from core.logging import configure_logging, get_logger


settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting AIC backend in %s environment", settings.environment.value)
    if settings.verify_dependencies:
        await verify_dependencies(settings)
        logger.info("PostgreSQL and Redis connections verified")
    yield
    logger.info("Stopping AIC backend")


app = FastAPI(
    title="AIC",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/")
async def root() -> dict[str, str]:
    return {"project": "AIC", "status": "running"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
