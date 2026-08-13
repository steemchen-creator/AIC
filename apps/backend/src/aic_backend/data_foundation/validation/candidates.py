"""Structural candidate contracts accepted before Domain construction."""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from aic_backend.domain.market_data import DataProvenance, InstrumentIdentity
from aic_backend.domain.market_data.models import InputValue


class CanonicalCandidate(Protocol):
    record_id: str
    record_type: str
    schema_version: str
    instrument: InstrumentIdentity | None
    event_time: datetime
    observed_at: datetime
    ingested_at: datetime
    provenance: DataProvenance
    payload: Mapping[str, InputValue]


class DailyBarCandidate(Protocol):
    record_id: str
    schema_version: str
    instrument: InstrumentIdentity
    trading_date: date
    event_time: datetime
    observed_at: datetime
    ingested_at: datetime
    provenance: DataProvenance
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Decimal
