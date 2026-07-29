"""Production Clock and ID generator implementations."""

from datetime import UTC, datetime
from uuid import uuid4


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIdGenerator:
    def new_id(self, prefix: str) -> str:
        if not prefix.strip():
            raise ValueError("prefix must not be empty")
        return f"{prefix}_{uuid4().hex}"
