"""FastAPI application factory."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from aic_backend.application.use_cases import GetDataRecord
from aic_backend.presentation.schemas import DataRecordResponse
from aic_backend.shared import Settings, configure_logging, get_logger, get_settings


async def no_startup_check(_: Settings) -> None:
    """Default no-op for isolated presentation tests."""


def create_app(
    get_data_record: GetDataRecord,
    settings: Settings | None = None,
    startup_check: Callable[[Settings], Awaitable[None]] = no_startup_check,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    logger = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("Starting AIC backend in %s environment", resolved_settings.environment.value)
        if resolved_settings.verify_dependencies:
            await startup_check(resolved_settings)
            logger.info("PostgreSQL and Redis connections verified")
        yield
        logger.info("Stopping AIC backend")

    app = FastAPI(title="AIC", version="0.2.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"project": "AIC", "status": "running"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Report process liveness; dependencies are verified during startup."""
        return {"status": "healthy"}

    @app.get("/data/{record_id}", response_model=DataRecordResponse)
    async def get_data(record_id: str) -> DataRecordResponse:
        record = await get_data_record.execute(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Data record not found")
        return DataRecordResponse(record_id=record.record_id, source=record.source,
                                  payload=dict(record.payload), observed_at=record.observed_at)

    return app
