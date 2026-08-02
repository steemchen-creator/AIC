"""Event bus contract."""

from datetime import datetime
from typing import Protocol


class Event(Protocol):
    """Minimal contract accepted by the shared event system."""

    @property
    def event_id(self) -> str: ...

    @property
    def occurred_at(self) -> datetime: ...

    @property
    def event_type(self) -> str: ...


class EventBus(Protocol):
    """Publish data foundation domain events."""

    async def publish(self, event: Event) -> None:
        """Publish an event to configured handlers."""
        ...
