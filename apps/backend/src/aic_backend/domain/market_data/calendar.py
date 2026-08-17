"""Canonical A-share trading-calendar facts and session policy."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from aic_backend.domain.market_data.enums import Market
from aic_backend.domain.market_data.models import DataProvenance

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class TradingSession:
    morning_open: datetime
    break_start: datetime
    break_end: datetime
    session_close: datetime

    def __post_init__(self) -> None:
        values = (self.morning_open, self.break_start, self.break_end, self.session_close)
        if any(value.tzinfo is None or value.utcoffset() is None for value in values):
            raise ValueError("session timestamps must include timezone information")
        if not self.morning_open < self.break_start < self.break_end < self.session_close:
            raise ValueError("session timestamps must be strictly ordered")


def standard_a_share_session(trading_date: date) -> TradingSession:
    """Return the V1 regular-session policy, not Provider-supplied session data."""

    def local(value: time) -> datetime:
        return datetime.combine(trading_date, value, SHANGHAI).astimezone(UTC)

    return TradingSession(local(time(9, 30)), local(time(11, 30)), local(time(13)), local(time(15)))


@dataclass(frozen=True, slots=True)
class TradingSessionDay:
    market: Market
    trading_date: date
    is_open: bool
    session: TradingSession | None
    retrieved_at: datetime
    provenance: DataProvenance

    def __post_init__(self) -> None:
        if self.market not in (Market.CN_SSE, Market.CN_SZSE):
            raise ValueError("calendar market must identify SSE or SZSE")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include timezone information")
        if self.is_open != (self.session is not None):
            raise ValueError("open days require a session and closed days must not have one")

    @property
    def identity(self) -> str:
        return f"{self.market.value}:{self.trading_date.isoformat()}"
