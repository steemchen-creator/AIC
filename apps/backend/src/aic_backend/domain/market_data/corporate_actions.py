"""Canonical corporate-action facts and derived adjusted DailyBar projections."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from aic_backend.domain.market_data.models import DataProvenance, InstrumentIdentity


class CorporateActionType(StrEnum):
    CASH_DIVIDEND = "CASH_DIVIDEND"
    STOCK_DIVIDEND = "STOCK_DIVIDEND"
    CAPITALIZATION = "CAPITALIZATION"
    RIGHTS_ISSUE = "RIGHTS_ISSUE"
    SPLIT = "SPLIT"
    MERGE = "MERGE"
    UNKNOWN = "UNKNOWN"


class AdjustmentMode(StrEnum):
    RAW = "RAW"
    FORWARD_ADJUSTED = "FORWARD_ADJUSTED"
    BACKWARD_ADJUSTED = "BACKWARD_ADJUSTED"


@dataclass(frozen=True, slots=True)
class AdjustmentFactor:
    factor_id: str
    instrument: InstrumentIdentity
    trading_date: date
    factor: Decimal
    factor_version: str
    retrieved_at: datetime
    provenance: DataProvenance

    def __post_init__(self) -> None:
        if not self.factor_id.strip() or not self.factor_version.strip():
            raise ValueError("factor identity and version must not be empty")
        if not isinstance(self.factor, Decimal) or self.factor <= 0:
            raise ValueError("factor must be a positive Decimal")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include timezone information")


@dataclass(frozen=True, slots=True)
class CorporateAction:
    action_id: str
    instrument: InstrumentIdentity
    action_type: CorporateActionType
    record_date: date | None
    ex_date: date | None
    pay_date: date | None
    effective_date: date | None
    cash_amount: Decimal | None
    share_ratio: Decimal | None
    rights_price: Decimal | None
    retrieved_at: datetime
    provenance: DataProvenance

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("action_id must not be empty")
        for field in ("cash_amount", "share_ratio", "rights_price"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, Decimal) or value < 0):
                raise ValueError(f"{field} must be a non-negative Decimal")
        if self.record_date is not None and self.ex_date is not None:
            if self.ex_date < self.record_date:
                raise ValueError("ex_date must not precede record_date")
        if self.ex_date is not None and self.pay_date is not None and self.pay_date < self.ex_date:
            raise ValueError("pay_date must not precede ex_date")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include timezone information")


@dataclass(frozen=True, slots=True)
class AdjustedDailyBar:
    projection_id: str
    source_record_id: str
    instrument: InstrumentIdentity
    trading_date: date
    mode: AdjustmentMode
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Decimal
    applied_factor: Decimal
    adjustment_version: str
