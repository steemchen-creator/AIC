from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from aic_backend.data_foundation import deterministic_record_id
from aic_backend.data_foundation.validation import (
    DailyBarValidator,
    ValidationContext,
)
from aic_backend.domain.market_data import (
    DailyBar,
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
)

NOW = datetime(2026, 1, 3, tzinfo=UTC)


class FixedClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


def provenance() -> DataProvenance:
    return DataProvenance(
        provider_id="fixture-provider",
        source_record_id="source-1",
        source_uri="https://example.test/bar/1",
        provider_timestamp=datetime(2026, 1, 2, 8, tzinfo=UTC),
        received_via_failover=False,
        failover_count=0,
        raw_payload_hash="a" * 64,
        transformation_version="daily-bar-v1",
    )


def bar(**changes: object) -> DailyBar:
    instrument = InstrumentIdentity(Market.CN_SSE, "600519", InstrumentType.EQUITY)
    event_time = datetime(2026, 1, 2, 7, tzinfo=UTC)
    values: dict[str, object] = {
        "record_id": deterministic_record_id(instrument, DailyBar.RECORD_TYPE, event_time),
        "schema_version": "1.0",
        "instrument": instrument,
        "trading_date": date(2026, 1, 2),
        "event_time": event_time,
        "observed_at": datetime(2026, 1, 2, 8, tzinfo=UTC),
        "ingested_at": datetime(2026, 1, 2, 8, 0, 1, tzinfo=UTC),
        "provenance": provenance(),
        "open": Decimal("10.10"),
        "high": Decimal("10.50"),
        "low": Decimal("9.90"),
        "close": Decimal("10.20"),
        "volume": 100,
        "turnover": Decimal("1010.00"),
    }
    values.update(changes)
    return DailyBar(**values)  # type: ignore[arg-type]


def validator(clock: FixedClock | None = None) -> DailyBarValidator:
    return DailyBarValidator(
        ValidationContext(
            clock or FixedClock(),
            max_future_skew=timedelta(minutes=5),
            supported_schema_versions=frozenset({"1.0"}),
        )
    )


def codes(value: DailyBar) -> tuple[str, ...]:
    return tuple(issue.code for issue in validator().validate(value).errors)


def test_valid_daily_bar_passes_without_mutation_or_decimal_change() -> None:
    value = bar()
    before = value
    result = validator().validate(value)

    assert result.valid is True
    assert result.errors == ()
    assert value == before
    assert value.open == Decimal("10.10")


@pytest.mark.parametrize(
    "changes",
    [
        {"high": Decimal("10.00")},
        {"high": Decimal("10.15"), "close": Decimal("10.20")},
        {"high": Decimal("9.80"), "low": Decimal("9.90")},
    ],
)
def test_high_below_open_close_or_low_is_invalid(changes: dict[str, object]) -> None:
    assert "DAILY_BAR_HIGH_INVALID" in codes(bar(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"low": Decimal("10.11")},
        {"low": Decimal("10.21"), "close": Decimal("10.20")},
    ],
)
def test_low_above_open_or_close_is_invalid(changes: dict[str, object]) -> None:
    assert "DAILY_BAR_LOW_INVALID" in codes(bar(**changes))


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_negative_price_is_invalid(field: str) -> None:
    assert "DAILY_BAR_PRICE_NEGATIVE" in codes(bar(**{field: Decimal("-0.01")}))


def test_negative_volume_and_turnover_are_invalid() -> None:
    result_codes = codes(bar(volume=-1, turnover=Decimal("-1")))
    assert "DAILY_BAR_VOLUME_NEGATIVE" in result_codes
    assert "DAILY_BAR_TURNOVER_NEGATIVE" in result_codes


def test_multiple_errors_are_collected_in_stable_order() -> None:
    value = bar(
        open=Decimal("-2"),
        high=Decimal("-3"),
        low=Decimal("1"),
        close=Decimal("-1"),
        volume=-1,
        turnover=Decimal("-1"),
    )
    first = validator().validate(value)

    assert len(first.errors) >= 7
    assert all(validator().validate(value) == first for _ in range(100))
    assert tuple((item.field, item.code) for item in first.errors) == tuple(
        sorted((item.field, item.code) for item in first.errors)
    )


def test_future_time_uses_injected_clock_and_tolerance() -> None:
    clock = FixedClock()
    within = bar(event_time=NOW + timedelta(minutes=5))
    beyond = bar(event_time=NOW + timedelta(minutes=5, microseconds=1))

    assert "TIMESTAMP_FUTURE" not in tuple(
        issue.code for issue in validator(clock).validate(within).errors
    )
    assert "TIMESTAMP_FUTURE" in tuple(
        issue.code for issue in validator(clock).validate(beyond).errors
    )
    assert clock.calls > 0


def test_validation_does_not_auto_correct_invalid_values() -> None:
    value = bar(high=Decimal("1"), volume=-5)
    original = replace(value)
    validator().validate(value)
    assert value == original
    assert value.high == Decimal("1")
    assert value.volume == -5


def test_ten_thousand_validations_are_linear_pure_work() -> None:
    value = bar()
    instance = validator()
    results = [instance.validate(value) for _ in range(10_000)]
    assert all(result.valid for result in results)


def test_structural_candidate_type_errors_are_collected() -> None:
    valid = bar()
    fields = {
        field: getattr(valid, field)
        for field in (
            "record_id",
            "schema_version",
            "instrument",
            "trading_date",
            "event_time",
            "observed_at",
            "ingested_at",
            "provenance",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
        )
    }
    fields.update(
        trading_date="2026-01-02",
        open=1.0,
        volume=True,
        turnover=1.0,
    )
    result = validator().validate(SimpleNamespace(**fields))  # type: ignore[arg-type]
    assert set(issue.code for issue in result.errors) == {
        "DAILY_BAR_PRICE_TYPE_INVALID",
        "DAILY_BAR_TRADING_DATE_INVALID",
        "DAILY_BAR_TURNOVER_TYPE_INVALID",
        "DAILY_BAR_VOLUME_TYPE_INVALID",
    }
