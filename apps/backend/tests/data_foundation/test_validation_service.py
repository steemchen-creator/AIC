from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from aic_backend.data_foundation.validation import (
    CanonicalRecordValidator,
    DailyBarValidator,
    DataValidationService,
    ValidationContext,
)
from aic_backend.domain.market_data import (
    CanonicalRecord,
    DailyBar,
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 3, tzinfo=UTC)


def values() -> tuple[CanonicalRecord, DailyBar]:
    instrument = InstrumentIdentity(Market.CN_SSE, "600519", InstrumentType.EQUITY)
    provenance = DataProvenance(
        "provider-1", None, None, None, False, 0, "a" * 64, "v1"
    )
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    canonical = CanonicalRecord(
        "rec-c", "MARKET_SNAPSHOT", "1.0", instrument, timestamp, timestamp,
        timestamp, provenance, {},
    )
    daily = DailyBar(
        "rec-d", "1.0", instrument, date(2026, 1, 2), timestamp, timestamp,
        timestamp, provenance, Decimal("1"), Decimal("1"), Decimal("1"),
        Decimal("1"), 1, Decimal("1"),
    )
    return canonical, daily


def service() -> DataValidationService:
    context = ValidationContext(FixedClock(), timedelta(minutes=5), frozenset({"1.0"}))
    return DataValidationService(
        CanonicalRecordValidator(context), DailyBarValidator(context)
    )


def test_service_dispatches_explicit_supported_types() -> None:
    canonical, daily = values()
    assert service().validate(canonical).valid is True
    assert service().validate(daily).valid is True


def test_service_does_not_use_reflection_or_swallow_unknown_type() -> None:
    with pytest.raises(TypeError, match="No validator registered"):
        service().validate(object())
