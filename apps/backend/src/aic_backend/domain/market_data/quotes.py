"""Source-neutral quote, reconciliation, and cross-asset pulse facts."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from aic_backend.domain.market_data.lineage import SourceLineage
from aic_backend.domain.market_data.models import InstrumentIdentity


def _text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include timezone information")
    return value.astimezone(UTC)


class QuoteSessionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    HALTED = "HALTED"
    UNKNOWN = "UNKNOWN"


class ReconciliationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    DEGRADED = "DEGRADED"
    CONFLICTED = "CONFLICTED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class MarketQuote:
    quote_id: str
    instrument: InstrumentIdentity
    event_time: datetime
    observed_at: datetime
    ingested_at: datetime
    last: Decimal
    bid: Decimal | None
    ask: Decimal | None
    previous_close: Decimal | None
    volume: int | None
    turnover: Decimal | None
    session_status: QuoteSessionStatus
    lineage: SourceLineage

    RECORD_TYPE = "MARKET_QUOTE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "quote_id", _text(self.quote_id, "quote_id"))
        for field in ("event_time", "observed_at", "ingested_at"):
            object.__setattr__(self, field, _utc(getattr(self, field), field))
        if (self.event_time, self.observed_at, self.ingested_at) != (
            self.lineage.event_time,
            self.lineage.observed_at,
            self.lineage.ingested_at,
        ):
            raise ValueError("quote timestamps must match source lineage")
        for field in ("last", "bid", "ask", "previous_close", "turnover"):
            value = getattr(self, field)
            if value is not None and not isinstance(value, Decimal):
                raise TypeError(f"{field} must be Decimal")
            if value is not None and value < 0:
                raise ValueError(f"{field} must not be negative")
        if self.last <= 0:
            raise ValueError("last must be positive")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid must not exceed ask")
        if self.volume is not None and (
            not isinstance(self.volume, int) or isinstance(self.volume, bool) or self.volume < 0
        ):
            raise ValueError("volume must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class QuoteReconciliation:
    reconciliation_id: str
    instrument: InstrumentIdentity
    as_of: datetime
    status: ReconciliationStatus
    contributing_quote_ids: tuple[str, ...]
    contributing_upstream_ids: tuple[str, ...]
    chosen_quote_id: str | None
    confidence: Decimal
    reasons: tuple[str, ...]
    policy_version: str

    def __post_init__(self) -> None:
        for field in ("reconciliation_id", "policy_version"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        object.__setattr__(self, "as_of", _utc(self.as_of, "as_of"))
        quote_ids = tuple(
            sorted({_text(value, "quote_id") for value in self.contributing_quote_ids})
        )
        upstream_ids = tuple(
            sorted({_text(value, "upstream_source_id") for value in self.contributing_upstream_ids})
        )
        object.__setattr__(self, "contributing_quote_ids", quote_ids)
        object.__setattr__(self, "contributing_upstream_ids", upstream_ids)
        object.__setattr__(
            self, "reasons", tuple(sorted({_text(v, "reason") for v in self.reasons}))
        )
        if not isinstance(self.confidence, Decimal) or not Decimal(
            "0"
        ) <= self.confidence <= Decimal("1"):
            raise ValueError("confidence must be Decimal between zero and one")
        if self.chosen_quote_id is not None:
            object.__setattr__(
                self, "chosen_quote_id", _text(self.chosen_quote_id, "chosen_quote_id")
            )
            if self.chosen_quote_id not in quote_ids:
                raise ValueError("chosen_quote_id must be a contributing quote")
        if self.status is ReconciliationStatus.CONFIRMED and len(upstream_ids) < 2:
            raise ValueError("confirmed reconciliation requires two independent upstreams")


class MarketPulseFamily(StrEnum):
    EQUITY_INDEX = "EQUITY_INDEX"
    SOVEREIGN_YIELD = "SOVEREIGN_YIELD"
    FX = "FX"
    GOLD = "GOLD"
    CRUDE_OIL = "CRUDE_OIL"
    VOLATILITY = "VOLATILITY"


class PublicationMode(StrEnum):
    REALTIME = "REALTIME"
    DELAYED = "DELAYED"
    DAILY_REFERENCE = "DAILY_REFERENCE"


@dataclass(frozen=True, slots=True)
class MarketSeriesIdentity:
    series_id: str
    family: MarketPulseFamily
    benchmark_owner: str
    definition: str
    geography: str
    unit: str
    publication_mode: PublicationMode
    currency: str | None = None
    tenor_or_contract: str | None = None

    def __post_init__(self) -> None:
        for field in ("series_id", "benchmark_owner", "definition", "geography", "unit"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        for field in ("currency", "tenor_or_contract"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _text(value, field))


@dataclass(frozen=True, slots=True)
class MarketPulseObservation:
    observation_id: str
    series: MarketSeriesIdentity
    value: Decimal
    event_time: datetime
    observed_at: datetime
    ingested_at: datetime
    lineage: SourceLineage

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _text(self.observation_id, "observation_id"))
        if not isinstance(self.value, Decimal):
            raise TypeError("value must be Decimal")
        for field in ("event_time", "observed_at", "ingested_at"):
            object.__setattr__(self, field, _utc(getattr(self, field), field))
        if (self.event_time, self.observed_at, self.ingested_at) != (
            self.lineage.event_time,
            self.lineage.observed_at,
            self.lineage.ingested_at,
        ):
            raise ValueError("pulse timestamps must match source lineage")
