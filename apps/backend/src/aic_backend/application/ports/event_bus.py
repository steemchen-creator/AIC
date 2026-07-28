"""Event bus contract."""

from typing import Protocol

from aic_backend.domain import DataRecordReceived


class EventBus(Protocol):
    """Publish data foundation domain events."""

    async def publish(self, event: DataRecordReceived) -> None:
        """Publish an event to configured handlers."""
        ...
