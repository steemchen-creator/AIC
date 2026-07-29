"""Domain events emitted by data foundation use cases."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class DataRecordReceived:
    """Signals that a provider record entered the owned data boundary."""

    event_id: str
    record_id: str
    source: str
    payload: Mapping[str, object]
    occurred_at: datetime

    @property
    def event_type(self) -> str:
        """Return the stable event name required by the shared Event Bus."""
        return "data_record_received"

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id must not be empty")
        if not self.record_id.strip():
            raise ValueError("record_id must not be empty")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include timezone information")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
