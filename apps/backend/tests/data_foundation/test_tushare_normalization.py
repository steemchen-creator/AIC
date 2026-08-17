from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aic_backend.data_foundation import create_raw_observation
from aic_backend.data_foundation.normalization import NormalizationError
from aic_backend.data_foundation.tushare_normalization import TushareDailyBarNormalizer
from aic_backend.domain.market_data import DataCapability, Market, RawObservation


def observation(*, failover_count: int = 0, **changes: object) -> RawObservation:
    row: dict[str, object] = {
        "ts_code": "000001.SZ", "trade_date": "20260102", "open": "10.1",
        "high": "10.5", "low": "9.9", "close": "10.2", "vol": 1234,
        "amount": "1",
    }
    row.update(changes)
    return create_raw_observation(
        observation_id="obs-1", provider_id="tushare_pro",
        capability=DataCapability.DAILY_BAR,
        received_at=datetime(2026, 1, 3, tzinfo=UTC), payload=row,
        source_metadata={"failover_count": failover_count},
    )


def test_units_event_time_and_determinism() -> None:
    normalizer = TushareDailyBarNormalizer()
    first = normalizer.normalize(observation())
    second = normalizer.normalize(observation())
    assert first == second
    assert first.volume == 123400
    assert first.turnover == Decimal("1000")
    assert first.event_time == datetime(2026, 1, 2, 7, tzinfo=UTC)
    assert first.instrument.market is Market.CN_SZSE
    assert first.provenance.transformation_version == "tushare-daily-bar/v1"


def test_sh_mapping_and_nan_rejection() -> None:
    record = TushareDailyBarNormalizer().normalize(observation(ts_code="600000.SH", vol=1))
    assert record.instrument.market is Market.CN_SSE
    assert record.volume == 100
    with pytest.raises(NormalizationError):
        TushareDailyBarNormalizer().normalize(observation(open="nan"))


def test_provenance_preserves_hash_and_failover_attribution() -> None:
    raw = observation(failover_count=1)
    record = TushareDailyBarNormalizer().normalize(raw)
    assert record.provenance.raw_payload_hash == raw.payload_hash
    assert record.provenance.received_via_failover is True
    assert record.provenance.failover_count == 1
    assert "token" not in (record.provenance.source_uri or "")


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"ts_code": "000001.BJ"}, "ts_code"),
        ({"ts_code": " "}, "ts_code"),
        ({"trade_date": "bad"}, "trade_date"),
        ({"close": None}, "close"),
        ({"close": True}, "close"),
        ({"close": "not-a-number"}, "close"),
        ({"vol": "1.001"}, "vol"),
    ],
)
def test_invalid_schema_fields_are_structured(
    changes: dict[str, object], field: str
) -> None:
    with pytest.raises(NormalizationError) as captured:
        TushareDailyBarNormalizer().normalize(observation(**changes))
    assert captured.value.field == field


def test_non_mapping_and_invalid_failover_metadata_are_rejected() -> None:
    raw = create_raw_observation(
        observation_id="obs-text", provider_id="tushare_pro",
        capability=DataCapability.DAILY_BAR,
        received_at=datetime(2026, 1, 3, tzinfo=UTC), payload="raw",
        source_metadata={"failover_count": 0},
    )
    with pytest.raises(NormalizationError):
        TushareDailyBarNormalizer().normalize(raw)
    with pytest.raises(NormalizationError):
        TushareDailyBarNormalizer().normalize(observation(failover_count=-1))
