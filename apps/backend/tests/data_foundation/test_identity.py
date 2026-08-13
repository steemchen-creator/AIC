from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from aic_backend.data_foundation import deterministic_record_id, raw_payload_hash
from aic_backend.domain.market_data import (
    InstrumentIdentity,
    InstrumentType,
    InvalidPayloadError,
    Market,
)


def instrument(
    market: Market = Market.CN_SSE, symbol: str = "600519"
) -> InstrumentIdentity:
    return InstrumentIdentity(market, symbol, InstrumentType.EQUITY)


def test_same_financial_fact_has_same_record_id() -> None:
    china = timezone(timedelta(hours=8))
    local_time = datetime(2026, 1, 2, 15, tzinfo=china)
    utc_time = datetime(2026, 1, 2, 7, tzinfo=UTC)

    assert deterministic_record_id(instrument(), "daily_bar", local_time, "2026-01-02") == (
        deterministic_record_id(instrument(), "DAILY_BAR", utc_time, "2026-01-02")
    )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (instrument(), instrument(Market.CN_SSE, "600000")),
        (instrument(), instrument(Market.CN_SZSE, "600519")),
    ],
)
def test_instrument_or_market_changes_record_id(
    left: InstrumentIdentity, right: InstrumentIdentity
) -> None:
    assert deterministic_record_id(left, "DAILY_BAR", datetime(2026, 1, 2, tzinfo=UTC)) != (
        deterministic_record_id(right, "DAILY_BAR", datetime(2026, 1, 2, tzinfo=UTC))
    )


def test_event_time_record_type_and_discriminator_change_record_id() -> None:
    first = datetime(2026, 1, 2, tzinfo=UTC)
    second = datetime(2026, 1, 3, tzinfo=UTC)
    base = deterministic_record_id(instrument(), "DAILY_BAR", first, "a")

    assert base != deterministic_record_id(instrument(), "DAILY_BAR", second, "a")
    assert base != deterministic_record_id(instrument(), "MARKET_SNAPSHOT", first, "a")
    assert base != deterministic_record_id(instrument(), "DAILY_BAR", first, "b")


def test_record_identity_is_repeatable_without_random_or_process_state() -> None:
    values = {
        deterministic_record_id(
            instrument(), "DAILY_BAR", datetime(2026, 1, 2, tzinfo=UTC), "day"
        )
        for _ in range(100)
    }
    assert len(values) == 1
    assert next(iter(values)).startswith("rec_")


def test_record_identity_rejects_blank_type_and_naive_time() -> None:
    with pytest.raises(ValueError, match="record_type"):
        deterministic_record_id(instrument(), " ", datetime(2026, 1, 2, tzinfo=UTC))
    with pytest.raises(ValueError, match="timezone"):
        deterministic_record_id(instrument(), "DAILY_BAR", datetime(2026, 1, 2))


def test_mapping_order_does_not_change_raw_hash() -> None:
    first = {"symbol": "600519", "bar": {"close": Decimal("10.20"), "volume": 100}}
    second = {"bar": {"volume": 100, "close": Decimal("10.20")}, "symbol": "600519"}

    assert raw_payload_hash(first) == raw_payload_hash(second)
    assert len(raw_payload_hash(first)) == 64


def test_raw_hash_has_stable_typed_serialization() -> None:
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    value = {
        "date": date(2026, 1, 2),
        "timestamp": timestamp,
        "values": [None, True, 1, "1", Decimal("1.0")],
    }

    assert raw_payload_hash(value) == raw_payload_hash(value)
    assert raw_payload_hash(b"same") != raw_payload_hash("same")
    assert raw_payload_hash({"value": 1}) != raw_payload_hash({"value": "1"})


def test_raw_hash_rejects_unsupported_values_keys_and_naive_datetime() -> None:
    with pytest.raises(InvalidPayloadError, match="unsupported"):
        raw_payload_hash({"value": object()})  # type: ignore[dict-item]
    with pytest.raises(InvalidPayloadError, match="keys"):
        raw_payload_hash({1: "value"})  # type: ignore[dict-item]
    with pytest.raises(InvalidPayloadError, match="timezone"):
        raw_payload_hash({"time": datetime(2026, 1, 2)})
    with pytest.raises(InvalidPayloadError, match="bytes, text, or a mapping"):
        raw_payload_hash(1)  # type: ignore[arg-type]
