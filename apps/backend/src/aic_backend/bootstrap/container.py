"""Concrete adapter composition for TASK-002."""

from dataclasses import dataclass

from aic_backend.application.use_cases import GetDataRecord
from aic_backend.infrastructure import InMemoryDataCache, InMemoryDataRepository, InMemoryEventBus
from aic_backend.providers import MockDataProvider
from aic_backend.providers.fixtures import build_mock_records


@dataclass(frozen=True, slots=True)
class Container:
    get_data_record: GetDataRecord


def build_container() -> Container:
    provider = MockDataProvider(build_mock_records())
    return Container(get_data_record=GetDataRecord(
        cache=InMemoryDataCache(),
        repository=InMemoryDataRepository(),
        provider=provider,
        event_bus=InMemoryEventBus(),
    ))
