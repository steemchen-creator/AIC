"""HTTP response schemas."""

from datetime import datetime

from pydantic import BaseModel


class DataRecordResponse(BaseModel):
    record_id: str
    source: str
    payload: dict[str, object]
    observed_at: datetime
