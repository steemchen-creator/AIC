from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from aic_backend.data_foundation import create_raw_observation, deterministic_record_id
from aic_backend.domain.market_data import (
    CanonicalRecord,
    DailyBar,
    DataCapability,
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    InvalidInstrumentError,
    InvalidPayloadError,
    InvalidProvenanceError,
    InvalidTimestampError,
    Market,
)

UTC_TIME = datetime(2026, 1, 2, 7, tzinfo=UTC)
HASH = "a" * 64


def instrument(
    market: Market = Market.CN_SSE,
    symbol: str = "600519",
    instrument_type: InstrumentType = InstrumentType.EQUITY,
) -> InstrumentIdentity:
    return InstrumentIdentity(market, symbol, instrument_type)


def provenance(**changes: object) -> DataProvenance:
    values: dict[str, object] = {
        "provider_id": "fixture-provider",
        "source_record_id": "source-1",
        "source_uri": "https://example.test/records/1",
        "provider_timestamp": UTC_TIME,
        "received_via_failover": False,
        "failover_count": 0,
        "raw_payload_hash": HASH,
        "transformation_version": "daily-bar-v1",
    }
    values.update(changes)
    return DataProvenance(**values)  # type: ignore[arg-type]


def test_instrument_identity_is_typed_normalized_and_unambiguous() -> None:
    sse = instrument(symbol=" 600519 ")
    szse = instrument(Market.CN_SZSE, "600519")
    etf = instrument(instrument_type=InstrumentType.ETF)

    assert sse.canonical_key == "CN.SSE.600519"
    assert sse != szse
    assert sse != etf
    with pytest.raises(FrozenInstanceError):
        sse.symbol = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("symbol", ["", " ", "SSE.600519"])
def test_instrument_rejects_invalid_symbol(symbol: str) -> None:
    with pytest.raises(InvalidInstrumentError):
        instrument(symbol=symbol)


def test_provenance_preserves_lineage_and_normalizes_timestamp() -> None:
    china_time = datetime(2026, 1, 2, 15, tzinfo=timezone(timedelta(hours=8)))
    value = provenance(
        provider_timestamp=china_time,
        received_via_failover=True,
        failover_count=1,
    )

    assert value.provider_id == "fixture-provider"
    assert value.source_record_id == "source-1"
    assert value.source_uri == "https://example.test/records/1"
    assert value.provider_timestamp == UTC_TIME
    assert value.received_via_failover is True
    assert value.failover_count == 1
    assert value.raw_payload_hash == HASH
    assert value.transformation_version == "daily-bar-v1"

    minimal = provenance(
        source_record_id=None,
        source_uri=None,
        provider_timestamp=None,
    )
    assert minimal.source_record_id is None
    assert minimal.source_uri is None
    assert minimal.provider_timestamp is None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"provider_id": " "}, "provider_id"),
        ({"transformation_version": ""}, "transformation_version"),
        ({"source_record_id": ""}, "source_record_id"),
        ({"raw_payload_hash": "bad"}, "SHA-256"),
        ({"failover_count": -1}, "negative"),
        ({"failover_count": 1}, "attribution"),
        ({"provider_timestamp": datetime(2026, 1, 1)}, "timezone"),
        ({"source_uri": "https://user:pass@example.test/x"}, "credentials"),
        ({"source_uri": "https://example.test/x?api_key=secret"}, "credentials"),
    ],
)
def test_provenance_rejects_invalid_or_secret_values(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises((InvalidProvenanceError, InvalidTimestampError), match=message):
        provenance(**changes)


def test_raw_observation_defensively_freezes_nested_values() -> None:
    payload: dict[str, object] = {
        "close": Decimal("10.20"),
        "levels": [1, 2],
        "observed": UTC_TIME,
    }
    metadata: dict[str, object] = {"page": {"number": 1}}
    observation = create_raw_observation(
        observation_id="obs-1",
        provider_id="fixture-provider",
        capability=DataCapability.DAILY_BAR,
        received_at=UTC_TIME,
        payload=payload,  # type: ignore[arg-type]
        source_metadata=metadata,  # type: ignore[arg-type]
    )
    payload["close"] = Decimal("99")
    metadata["page"] = {"number": 2}

    assert observation.payload["close"] == Decimal("10.20")  # type: ignore[index]
    assert observation.payload["levels"] == (1, 2)  # type: ignore[index]
    assert observation.payload["observed"] == UTC_TIME  # type: ignore[index]
    assert observation.source_metadata["page"] == {"number": 1}
    with pytest.raises(TypeError):
        observation.source_metadata["new"] = 1  # type: ignore[index]


@pytest.mark.parametrize("field", ["observation_id", "provider_id"])
def test_raw_observation_rejects_blank_identity(field: str) -> None:
    values = {
        "observation_id": "obs-1",
        "provider_id": "provider-1",
        "capability": DataCapability.DAILY_BAR,
        "received_at": UTC_TIME,
        "payload": {},
        "source_metadata": {},
    }
    values[field] = " "
    with pytest.raises(ValueError, match=field):
        create_raw_observation(**values)  # type: ignore[arg-type]


def test_raw_observation_rejects_naive_time_and_unsupported_payload() -> None:
    with pytest.raises(InvalidTimestampError):
        create_raw_observation(
            observation_id="obs-1",
            provider_id="provider-1",
            capability=DataCapability.DAILY_BAR,
            received_at=datetime(2026, 1, 1),
            payload={},
            source_metadata={},
        )


@pytest.mark.parametrize("payload", [b"raw", "raw"])
def test_raw_observation_accepts_binary_and_text_payload(payload: bytes | str) -> None:
    observation = create_raw_observation(
        observation_id="obs-1",
        provider_id="provider-1",
        capability=DataCapability.DAILY_BAR,
        received_at=UTC_TIME,
        payload=payload,
        source_metadata={},
    )
    assert observation.payload == payload


def test_raw_observation_rejects_invalid_mapping_key_and_supplied_hash() -> None:
    with pytest.raises(InvalidPayloadError, match="keys"):
        create_raw_observation(
            observation_id="obs-1",
            provider_id="provider-1",
            capability=DataCapability.DAILY_BAR,
            received_at=UTC_TIME,
            payload={"valid": 1},
            source_metadata={"": 1},
        )

    from aic_backend.domain.market_data import RawObservation

    with pytest.raises(InvalidPayloadError, match="payload_hash"):
        RawObservation(
            observation_id="obs-1",
            provider_id="provider-1",
            capability=DataCapability.DAILY_BAR,
            received_at=UTC_TIME,
            payload={},
            payload_hash="not-a-hash",
            source_metadata={},
        )
    with pytest.raises(InvalidPayloadError):
        create_raw_observation(
            observation_id="obs-1",
            provider_id="provider-1",
            capability=DataCapability.DAILY_BAR,
            received_at=UTC_TIME,
            payload={"opaque": object()},  # type: ignore[dict-item]
            source_metadata={},
        )


def test_canonical_record_preserves_three_timestamp_semantics_and_freezes_payload() -> None:
    china = timezone(timedelta(hours=8))
    payload: dict[str, object] = {"tags": ["official"], "price": Decimal("10.2")}
    value = CanonicalRecord(
        record_id="rec-1",
        record_type="MARKET_SNAPSHOT",
        schema_version="1.0",
        instrument=instrument(),
        event_time=datetime(2026, 1, 2, 15, tzinfo=china),
        observed_at=datetime(2026, 1, 2, 15, 0, 1, tzinfo=china),
        ingested_at=datetime(2026, 1, 2, 15, 0, 2, tzinfo=china),
        provenance=provenance(),
        payload=payload,  # type: ignore[arg-type]
    )
    payload["price"] = Decimal("99")

    assert value.event_time == datetime(2026, 1, 2, 7, tzinfo=UTC)
    assert value.observed_at == datetime(2026, 1, 2, 7, 0, 1, tzinfo=UTC)
    assert value.ingested_at == datetime(2026, 1, 2, 7, 0, 2, tzinfo=UTC)
    assert value.payload == {"tags": ("official",), "price": Decimal("10.2")}


@pytest.mark.parametrize("field", ["record_id", "record_type", "schema_version"])
def test_canonical_record_rejects_blank_required_text(field: str) -> None:
    values = {
        "record_id": "rec-1",
        "record_type": "MARKET_SNAPSHOT",
        "schema_version": "1.0",
        "instrument": instrument(),
        "event_time": UTC_TIME,
        "observed_at": UTC_TIME,
        "ingested_at": UTC_TIME,
        "provenance": provenance(),
        "payload": {},
    }
    values[field] = " "
    with pytest.raises(ValueError, match=field):
        CanonicalRecord(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["event_time", "observed_at", "ingested_at"])
def test_canonical_record_rejects_naive_timestamps(field: str) -> None:
    values = {
        "record_id": "rec-1",
        "record_type": "MARKET_SNAPSHOT",
        "schema_version": "1.0",
        "instrument": instrument(),
        "event_time": UTC_TIME,
        "observed_at": UTC_TIME,
        "ingested_at": UTC_TIME,
        "provenance": provenance(),
        "payload": {},
    }
    values[field] = datetime(2026, 1, 1)
    with pytest.raises(InvalidTimestampError, match=field):
        CanonicalRecord(**values)  # type: ignore[arg-type]


def test_daily_bar_uses_decimal_and_keeps_market_trading_date() -> None:
    china = timezone(timedelta(hours=8))
    value = DailyBar(
        record_id=deterministic_record_id(
            instrument(), DailyBar.RECORD_TYPE, datetime(2026, 1, 2, 0, tzinfo=china)
        ),
        schema_version="1.0",
        instrument=instrument(),
        trading_date=date(2026, 1, 2),
        event_time=datetime(2026, 1, 2, 0, tzinfo=china),
        observed_at=UTC_TIME,
        ingested_at=UTC_TIME,
        provenance=provenance(),
        open=Decimal("100.10"),
        high=Decimal("103.20"),
        low=Decimal("99.80"),
        close=Decimal("102.30"),
        volume=123456,
        turnover=Decimal("12500000.01"),
    )

    assert value.open + Decimal("0.10") == Decimal("100.20")
    assert value.trading_date == date(2026, 1, 2)
    assert value.event_time.date() == date(2026, 1, 1)
    assert value.trading_date != value.event_time.date()


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "turnover"])
def test_daily_bar_rejects_binary_float_for_financial_values(field: str) -> None:
    values = {
        "record_id": "rec-1",
        "schema_version": "1.0",
        "instrument": instrument(),
        "trading_date": date(2026, 1, 2),
        "event_time": UTC_TIME,
        "observed_at": UTC_TIME,
        "ingested_at": UTC_TIME,
        "provenance": provenance(),
        "open": Decimal("1"),
        "high": Decimal("1"),
        "low": Decimal("1"),
        "close": Decimal("1"),
        "volume": 1,
        "turnover": Decimal("1"),
    }
    values[field] = 1.0
    with pytest.raises(TypeError, match=field):
        DailyBar(**values)  # type: ignore[arg-type]


def test_daily_bar_does_not_apply_phase_2_financial_validation() -> None:
    value = DailyBar(
        record_id="rec-1",
        schema_version="1.0",
        instrument=instrument(),
        trading_date=date(2026, 1, 2),
        event_time=UTC_TIME,
        observed_at=UTC_TIME,
        ingested_at=UTC_TIME,
        provenance=provenance(),
        open=Decimal("10"),
        high=Decimal("1"),
        low=Decimal("20"),
        close=Decimal("10"),
        volume=-1,
        turnover=Decimal("-1"),
    )

    assert value.high == Decimal("1")


def test_daily_bar_rejects_boolean_volume() -> None:
    with pytest.raises(TypeError, match="volume"):
        DailyBar(
            record_id="rec-1",
            schema_version="1.0",
            instrument=instrument(),
            trading_date=date(2026, 1, 2),
            event_time=UTC_TIME,
            observed_at=UTC_TIME,
            ingested_at=UTC_TIME,
            provenance=provenance(),
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            volume=True,  # type: ignore[arg-type]
            turnover=Decimal("1"),
        )
