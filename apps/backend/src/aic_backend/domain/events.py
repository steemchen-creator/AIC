"""Domain events emitted by data foundation use cases."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DataRecordReceived:
    """Signals that a provider record entered the owned data boundary."""

    record_id: str
    source: str
    occurred_at: datetime
