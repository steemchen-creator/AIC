from datetime import UTC, datetime

import pytest

from aic_backend.provider_runtime import (
    CapabilityMode,
    HealthCheckResult,
    HealthStatus,
    ProviderCapability,
    ProviderDefinition,
    ProviderFactory,
    ProviderMetadata,
    ProviderType,
)
from aic_backend.provider_runtime.errors import InvalidProviderDefinitionError

NOW = datetime(2026, 7, 29, tzinfo=UTC)
CAPABILITY = ProviderCapability("market.quote.snapshot", "1.0.0", CapabilityMode.SNAPSHOT)


class StubProvider:
    def __init__(self, definition: ProviderDefinition, *, mismatched: bool = False) -> None:
        self._metadata = ProviderMetadata(
            provider_id="other_provider" if mismatched else definition.provider_id,
            display_name="Mock Market",
            provider_type=ProviderType.MOCK,
            version="1.0.0",
            priority=definition.priority,
            enabled=definition.enabled,
        )
        self._capabilities = definition.capabilities

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return self._capabilities

    async def initialize(self) -> None: ...

    async def shutdown(self) -> None: ...

    async def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(HealthStatus.HEALTHY, NOW)


def definition(**overrides: object) -> ProviderDefinition:
    values: dict[str, object] = {
        "provider_id": "mock_primary",
        "implementation": "mock.market",
        "enabled": True,
        "priority": 100,
        "capabilities": frozenset({CAPABILITY}),
        "config": {"fixture_set": "default"},
    }
    values.update(overrides)
    return ProviderDefinition(**values)  # type: ignore[arg-type]


def test_factory_creates_only_allowlisted_implementation() -> None:
    factory = ProviderFactory({"mock.market": StubProvider})

    provider = factory.create(definition())

    assert provider.metadata.provider_id == "mock_primary"


def test_factory_copies_allowlist_at_construction() -> None:
    builders = {"mock.market": StubProvider}
    factory = ProviderFactory(builders)
    builders.clear()

    assert factory.create(definition()).metadata.provider_id == "mock_primary"


def test_factory_rejects_unknown_implementation() -> None:
    factory = ProviderFactory({})

    with pytest.raises(InvalidProviderDefinitionError, match="Unknown") as captured:
        factory.create(definition())

    assert captured.value.provider_id == "mock_primary"


def test_factory_normalizes_builder_failure_without_leaking_cause() -> None:
    def failing_builder(_: ProviderDefinition) -> StubProvider:
        raise RuntimeError("private SDK detail")

    factory = ProviderFactory({"mock.market": failing_builder})

    with pytest.raises(InvalidProviderDefinitionError, match="could not be created") as captured:
        factory.create(definition())

    assert "private SDK detail" not in str(captured.value)
    assert isinstance(captured.value.__cause__, RuntimeError)


def test_factory_rejects_provider_that_does_not_match_definition() -> None:
    factory = ProviderFactory(
        {"mock.market": lambda value: StubProvider(value, mismatched=True)}
    )

    with pytest.raises(InvalidProviderDefinitionError, match="does not match"):
        factory.create(definition())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("provider_id", "Bad-ID", "provider_id"),
        ("implementation", "dynamic", "implementation"),
        ("priority", 1001, "priority"),
        ("capabilities", frozenset(), "capabilities"),
        ("max_concurrency", 0, "max_concurrency"),
        ("queue_timeout_ms", 0, "queue_timeout_ms"),
    ],
)
def test_provider_definition_rejects_invalid_values(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        definition(**{field: value})


def test_provider_definition_copies_configuration() -> None:
    config = {"fixture_set": "default"}
    value = definition(config=config)
    config["fixture_set"] = "changed"

    assert value.config == {"fixture_set": "default"}
    with pytest.raises(TypeError):
        value.config["fixture_set"] = "changed"  # type: ignore[index]
