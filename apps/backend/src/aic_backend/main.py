"""ASGI entry point."""

from aic_backend.bootstrap import build_container
from aic_backend.infrastructure.dependencies import verify_dependencies
from aic_backend.presentation import create_app

container = build_container()
app = create_app(
    get_data_record=container.get_data_record,
    startup_check=verify_dependencies,
)
