"""Source-neutral ETF, index-reference, valuation, and execution-profile facts."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from aic_backend.domain.market_data.enums import InstrumentType, Market
from aic_backend.domain.market_data.instrument import InstrumentMaster, ListingStatus
from aic_backend.domain.market_data.models import DataProvenance, InstrumentIdentity


class Currency(StrEnum):
    CNY = "CNY"
    USD = "USD"
    UNKNOWN = "UNKNOWN"


class ETFChannel(StrEnum):
    DOMESTIC = "DOMESTIC"
    QDII = "QDII"
    UNKNOWN = "UNKNOWN"


class ExposureMarket(StrEnum):
    CHINA = "CHINA"
    US = "US"
    UNKNOWN = "UNKNOWN"


class ExposureCategory(StrEnum):
    US_GROWTH = "US_GROWTH"
    NASDAQ_100 = "NASDAQ_100"
    CHINA_BROAD_MARKET = "CHINA_BROAD_MARKET"
    CHINA_SECTOR = "CHINA_SECTOR"
    COMMODITY = "COMMODITY"
    BOND = "BOND"
    UNKNOWN = "UNKNOWN"


class ExposureFamily(StrEnum):
    NASDAQ = "NASDAQ"
    CHINA = "CHINA"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class SettlementCapability(StrEnum):
    T0 = "T0"
    T1 = "T1"
    UNKNOWN = "UNKNOWN"


def _text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _optional_text(value: str | None) -> str | None:
    return None if value is None else value.strip() or None


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include timezone information")
    return value


def _listed_identity(value: InstrumentIdentity, expected: InstrumentType) -> None:
    if value.instrument_type is not expected:
        raise ValueError(f"instrument must be {expected.value}")
    if expected is InstrumentType.ETF and value.market not in (Market.CN_SSE, Market.CN_SZSE):
        raise ValueError("ETF must be listed on SSE or SZSE")
    if expected is InstrumentType.INDEX and value.market is not Market.INDEX_REFERENCE:
        raise ValueError("index must use the non-tradable reference namespace")


@dataclass(frozen=True, slots=True)
class IndexReference:
    index_identity: InstrumentIdentity
    display_name: str
    publisher: str | None
    base_date: date | None
    base_value: Decimal | None
    exposure_market: ExposureMarket
    point_currency: Currency
    provenance: DataProvenance
    available_at: datetime

    def __post_init__(self) -> None:
        _listed_identity(self.index_identity, InstrumentType.INDEX)
        object.__setattr__(self, "display_name", _text(self.display_name, "display_name"))
        object.__setattr__(self, "publisher", _optional_text(self.publisher))
        if self.base_value is not None and (
            not isinstance(self.base_value, Decimal) or self.base_value <= 0
        ):
            raise ValueError("base_value must be a positive Decimal when present")
        _aware(self.available_at, "available_at")

    @property
    def tradable(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class ETFInstrumentProfile:
    instrument: InstrumentIdentity
    display_name: str
    expanded_name: str | None
    listing_date: date | None
    delisting_date: date | None
    listing_status: ListingStatus
    channel: ETFChannel
    benchmark_index_identity: InstrumentIdentity | None
    fund_manager: str | None
    management_fee: Decimal | None
    underlying_market: ExposureMarket
    underlying_currency: Currency
    trading_currency: Currency
    exposure_category: ExposureCategory
    provenance: DataProvenance
    available_at: datetime
    exposure_family: ExposureFamily = ExposureFamily.UNKNOWN

    def __post_init__(self) -> None:
        _listed_identity(self.instrument, InstrumentType.ETF)
        object.__setattr__(self, "display_name", _text(self.display_name, "display_name"))
        object.__setattr__(self, "expanded_name", _optional_text(self.expanded_name))
        object.__setattr__(self, "fund_manager", _optional_text(self.fund_manager))
        if self.delisting_date is not None and self.listing_date is None:
            raise ValueError("delisting_date requires listing_date")
        if (
            self.listing_date is not None
            and self.delisting_date is not None
            and self.delisting_date < self.listing_date
        ):
            raise ValueError("delisting_date must not precede listing_date")
        if self.benchmark_index_identity is not None:
            _listed_identity(self.benchmark_index_identity, InstrumentType.INDEX)
        if self.management_fee is not None and (
            not isinstance(self.management_fee, Decimal) or self.management_fee < 0
        ):
            raise ValueError("management_fee must be a non-negative Decimal when present")
        if self.trading_currency is not Currency.CNY:
            raise ValueError("SPEC-009 supports CNY trading accounts only")
        _aware(self.available_at, "available_at")


@dataclass(frozen=True, slots=True)
class ETFMasterBundle:
    master: InstrumentMaster
    profile: ETFInstrumentProfile
    relationship: "ETFTracksIndex | None"

    def __post_init__(self) -> None:
        if self.master.instrument != self.profile.instrument:
            raise ValueError("master and ETF profile must identify the same instrument")
        if (
            self.relationship is not None
            and self.relationship.etf_instrument != self.profile.instrument
        ):
            raise ValueError("ETF relationship must identify the bundled instrument")
        if (
            self.relationship is not None
            and self.profile.benchmark_index_identity != self.relationship.benchmark_index
        ):
            raise ValueError("ETF relationship must match the profile benchmark")


@dataclass(frozen=True, slots=True)
class ETFTracksIndex:
    relationship_id: str
    etf_instrument: InstrumentIdentity
    benchmark_index: InstrumentIdentity
    effective_from: date | None
    effective_to: date | None
    current_relationship_only: bool
    provenance: DataProvenance
    available_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "relationship_id", _text(self.relationship_id, "relationship_id"))
        _listed_identity(self.etf_instrument, InstrumentType.ETF)
        _listed_identity(self.benchmark_index, InstrumentType.INDEX)
        if self.effective_to is not None and self.effective_from is None:
            raise ValueError("effective_to requires effective_from")
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to must not precede effective_from")
        _aware(self.available_at, "available_at")


@dataclass(frozen=True, slots=True)
class ETFValuationSnapshot:
    valuation_id: str
    instrument: InstrumentIdentity
    trading_date: date
    nav: Decimal | None
    close_price: Decimal | None
    share_size: Decimal | None
    premium_discount_pct: Decimal | None
    provenance: DataProvenance
    available_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "valuation_id", _text(self.valuation_id, "valuation_id"))
        _listed_identity(self.instrument, InstrumentType.ETF)
        for field in ("nav", "close_price"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, Decimal) or value <= 0):
                raise ValueError(f"{field} must be a positive Decimal when present")
        if self.share_size is not None and (
            not isinstance(self.share_size, Decimal) or self.share_size < 0
        ):
            raise ValueError("share_size must be a non-negative Decimal when present")
        if self.premium_discount_pct is not None and not isinstance(
            self.premium_discount_pct, Decimal
        ):
            raise TypeError("premium_discount_pct must be Decimal when present")
        _aware(self.available_at, "available_at")


@dataclass(frozen=True, slots=True)
class InstrumentExecutionProfile:
    profile_id: str
    instrument: InstrumentIdentity
    trading_currency: Currency
    board_lot: int
    settlement_capability: SettlementCapability
    price_limit_policy_reference: str
    calendar_reference: Market
    source: str
    available_at: datetime
    effective_from: date
    policy_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        if self.instrument.instrument_type not in (InstrumentType.EQUITY, InstrumentType.ETF):
            raise ValueError("execution profile requires a tradable equity or ETF")
        if self.instrument.market not in (Market.CN_SSE, Market.CN_SZSE):
            raise ValueError("execution profile venue must be SSE or SZSE")
        if self.trading_currency is not Currency.CNY:
            raise ValueError("SPEC-009 execution supports CNY only")
        if self.board_lot <= 0:
            raise ValueError("board_lot must be positive")
        object.__setattr__(
            self,
            "price_limit_policy_reference",
            _text(self.price_limit_policy_reference, "price_limit_policy_reference"),
        )
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(self, "policy_version", _text(self.policy_version, "policy_version"))
        _aware(self.available_at, "available_at")

    @property
    def same_day_round_trip_allowed(self) -> bool:
        return self.settlement_capability is SettlementCapability.T0
