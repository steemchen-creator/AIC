from datetime import UTC, datetime

import pytest

from aic_backend.application.ports import DataProvider
from aic_backend.domain import DataRecord
from aic_backend.providers import MockDataProvider
from aic_backend.providers.fixtures import build_mock_records


@pytest.mark.asyncio
async def test_mock_provider_implements_contract_without_side_effects() -> None:
    expected = DataRecord(
        record_id="sample-1",
        source="mock",
        payload={"value": 42},
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    provider: DataProvider = MockDataProvider([expected])

    result = await provider.fetch("sample-1")

    assert result is expected


@pytest.mark.asyncio
async def test_mock_provider_returns_none_for_unknown_record() -> None:
    provider = MockDataProvider()

    assert await provider.fetch("missing") is None


def test_mock_fixture_is_deterministic() -> None:
    assert build_mock_records() == build_mock_records()
    assert build_mock_records()[0].record_id == "sample-1"
    assert build_mock_records()[0] is not build_mock_records()[0]
