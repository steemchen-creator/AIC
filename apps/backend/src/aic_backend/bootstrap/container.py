"""Concrete adapter composition for TASK-002."""

from dataclasses import dataclass
from datetime import UTC, datetime

from aic_backend.application.use_cases import GetDataRecord
from aic_backend.domain import DataRecord
from aic_backend.infrastructure import InMemoryDataCache, InMemoryDataRepository, InMemoryEventBus
from aic_backend.providers import MockDataProvider


@dataclass(frozen=True, slots=True)
class Container:
    get_data_record: GetDataRecord


def build_container() -> Container:
    provider = MockDataProvider([DataRecord(
        record_id="sample-1",
        source="mock",
        payload={"value": 42},
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )])
    return Container(get_data_record=GetDataRecord(
        cache=InMemoryDataCache(),
        repository=InMemoryDataRepository(),
        provider=provider,
        event_bus=InMemoryEventBus(),
    ))
