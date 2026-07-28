"""Domain models for source-neutral data."""

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class DataRecord:
    """An immutable data item obtained from a configured provider."""

    record_id: str
    source: str
    payload: Mapping[str, object]
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.record_id.strip():
            raise ValueError("record_id must not be empty")
        if not self.source.strip():
            raise ValueError("source must not be empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must include timezone information")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
