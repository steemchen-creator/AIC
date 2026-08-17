from datetime import UTC, datetime

from aic_backend.provider_runtime import (
    CapabilityMode,
    ProviderCapability,
    ProviderInvocationResult,
    ProviderRequestContext,
    ProviderRuntime,
)
from aic_backend.provider_runtime.models import ProviderRegistrySnapshot

NOW = datetime(2026, 1, 3, tzinfo=UTC)
CAPABILITY = ProviderCapability("market.daily.read", "1.0.0", CapabilityMode.BATCH)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class StubRegistry:
    async def snapshot(self) -> ProviderRegistrySnapshot:
        return ProviderRegistrySnapshot((), NOW)


class StubFailover:
    def __init__(self) -> None:
        self.arguments: tuple[object, ...] = ()

    async def execute(self, *arguments):
        self.arguments = arguments
        return ProviderInvocationResult(
            "request_1", "tushare_pro", True, {"rows": []}, None, 1, NOW, NOW
        )


async def test_runtime_supplies_current_snapshots_to_failover() -> None:
    failover = StubFailover()
    runtime = ProviderRuntime(StubRegistry(), failover, FixedClock())  # type: ignore[arg-type]
    context = ProviderRequestContext("request_1", CAPABILITY, 1000)
    result = await runtime.execute(context, {"trade_date": "20260102"})
    assert result.provider_id == "tushare_pro"
    assert failover.arguments[0] is context
    assert failover.arguments[1] == {"trade_date": "20260102"}
    assert isinstance(failover.arguments[2], ProviderRegistrySnapshot)
    assert failover.arguments[3] == {}
    assert failover.arguments[4] == NOW
