"""Canonical A-share instrument master and daily trading-status facts."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from aic_backend.domain.market_data.enums import InstrumentType, Market
from aic_backend.domain.market_data.models import DataProvenance, InstrumentIdentity


class ListingStatus(StrEnum):
    LISTED = "LISTED"
    DELISTED = "DELISTED"
    UNKNOWN = "UNKNOWN"


class InstrumentTradingState(StrEnum):
    TRADING = "TRADING"
    SUSPENDED = "SUSPENDED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class InstrumentMaster:
    instrument: InstrumentIdentity
    display_name: str
    listing_date: date | None
    delisting_date: date | None
    listing_status: ListingStatus
    retrieved_at: datetime
    provenance: DataProvenance

    def __post_init__(self) -> None:
        if self.instrument.market not in (Market.CN_SSE, Market.CN_SZSE):
            raise ValueError("instrument market must identify SSE or SZSE")
        if self.instrument.instrument_type is not InstrumentType.EQUITY:
            raise ValueError("Phase 9 instrument master supports equities only")
        name = self.display_name.strip()
        if not name:
            raise ValueError("display_name must not be empty")
        object.__setattr__(self, "display_name", name)
        if self.delisting_date is not None and self.listing_date is None:
            raise ValueError("delisting_date requires listing_date")
        if (
            self.listing_date is not None
            and self.delisting_date is not None
            and self.delisting_date < self.listing_date
        ):
            raise ValueError("delisting_date must not precede listing_date")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include timezone information")


@dataclass(frozen=True, slots=True)
class InstrumentTradingStatus:
    instrument: InstrumentIdentity
    trading_date: date
    state: InstrumentTradingState
    reason: str | None
    retrieved_at: datetime
    provenance: DataProvenance

    def __post_init__(self) -> None:
        if self.instrument.market not in (Market.CN_SSE, Market.CN_SZSE):
            raise ValueError("instrument market must identify SSE or SZSE")
        if self.reason is not None:
            reason = self.reason.strip()
            object.__setattr__(self, "reason", reason or None)
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include timezone information")
