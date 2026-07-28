from celery import Celery

from core.config import get_settings
from core.exceptions import ConfigurationError


settings = get_settings()
if not settings.celery_broker_url:
    raise ConfigurationError("AIC_CELERY_BROKER_URL is required to initialize Celery")

celery_app = Celery(
    "aic",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
