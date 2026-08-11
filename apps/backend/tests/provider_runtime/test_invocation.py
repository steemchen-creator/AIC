import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from aic_backend.infrastructure import InMemoryEventBus
from aic_backend.provider_runtime import (
    CapabilityMode,
    HealthCheckResult,
    HealthStatus,
    ProviderCapability,
    ProviderInvocationManager,
    ProviderInvocationRequest,
    ProviderInvocationResponse,
    ProviderLifecycleManager,
    ProviderMetadata,
    ProviderRegistry,
    ProviderType,
)
from aic_backend.provider_runtime.errors import (
    CapabilityNotSupportedError,
    ProviderExecutionError,
    ProviderInvalidResponseError,
    ProviderPermanentError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

NOW = datetime(2026, 8, 11, tzinfo=UTC)
CAPABILITY = ProviderCapability("market.quote.snapshot", "1.0.0", CapabilityMode.SNAPSHOT)
OTHER = ProviderCapability("news.market.snapshot", "1.0.0", CapabilityMode.SNAPSHOT)


class AdvancingClock:
    def __init__(self) -> None:
        self.value = NOW

    def now(self) -> datetime:
        current = self.value
        self.value += timedelta(milliseconds=5)
        return current


class FixedIdGenerator:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}_fixed"


class StubProvider:
    def __init__(self) -> None:
        self._metadata = ProviderMetadata(
            "mock_primary", "Mock", ProviderType.MOCK, "1.0.0"
        )
        self.mode = "success"
        self.release: asyncio.Event | None = None
        self.entered = asyncio.Event()
        self.cancelled = False
        self.active = 0
        self.max_active = 0

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return frozenset({CAPABILITY})

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(HealthStatus.HEALTHY, NOW)

    async def invoke(self, request: ProviderInvocationRequest) -> object:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.entered.set()
        try:
            if self.release is not None:
                await self.release.wait()
            if self.mode == "known_error":
                raise ProviderPermanentError(
                    "Provider rejected the request.",
                    request_id=request.request_id,
                    provider_id=request.provider_id,
                )
            if self.mode == "exception":
                raise RuntimeError("token=secret private path C:/internal")
            if self.mode == "invalid":
                return {"invalid": True}
            return ProviderInvocationResponse(payload={"price": 42})
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.active -= 1


async def build_runtime(
    *, limit: int = 1, initialize: bool = True
) -> tuple[ProviderInvocationManager, StubProvider]:
    clock = AdvancingClock()
    registry = ProviderRegistry(clock)
    lifecycle = ProviderLifecycleManager(
        registry, InMemoryEventBus(), clock, FixedIdGenerator()
    )
    provider = StubProvider()
    await lifecycle.register(provider)
    if initialize:
        await lifecycle.initialize("mock_primary")
    return ProviderInvocationManager(registry, clock, {"mock_primary": limit}), provider


def request(
    *, timeout_ms: int = 100, capability: ProviderCapability = CAPABILITY
) -> ProviderInvocationRequest:
    return ProviderInvocationRequest(
        request_id="req_1",
        provider_id="mock_primary",
        capability=capability,
        payload={"symbol": "TEST"},
        timeout_ms=timeout_ms,
        created_at=NOW,
    )


async def test_successful_invocation_is_standardized() -> None:
    manager, _ = await build_runtime()
    result = await manager.invoke(request())
    assert result.success is True
    assert result.data == {"price": 42}
    assert result.error is None
    assert result.latency_ms == 5


async def test_known_provider_error_is_preserved() -> None:
    manager, provider = await build_runtime()
    provider.mode = "known_error"
    with pytest.raises(ProviderPermanentError, match="rejected"):
        await manager.invoke(request())
    provider.mode = "success"
    assert (await manager.invoke(request())).success is True


async def test_provider_exception_is_sanitized_and_preserves_cause() -> None:
    manager, provider = await build_runtime()
    provider.mode = "exception"
    with pytest.raises(ProviderExecutionError, match="invocation failed") as raised:
        await manager.invoke(request())
    assert "secret" not in str(raised.value)
    assert isinstance(raised.value.__cause__, RuntimeError)
    provider.mode = "success"
    assert (await manager.invoke(request())).success is True


async def test_invalid_response_is_rejected() -> None:
    manager, provider = await build_runtime()
    provider.mode = "invalid"
    with pytest.raises(ProviderInvalidResponseError, match="invalid response"):
        await manager.invoke(request())
    provider.mode = "success"
    assert (await manager.invoke(request())).success is True


async def test_timeout_cancels_provider_and_releases_capacity() -> None:
    manager, provider = await build_runtime()
    provider.release = asyncio.Event()
    with pytest.raises(ProviderTimeoutError, match="timed out"):
        await manager.invoke(request(timeout_ms=10))
    assert provider.cancelled is True
    provider.release = None
    assert (await manager.invoke(request())).success is True


async def test_task_cancellation_propagates_and_releases_capacity() -> None:
    manager, provider = await build_runtime()
    provider.release = asyncio.Event()
    task = asyncio.create_task(manager.invoke(request(timeout_ms=1000)))
    await provider.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.cancelled is True
    provider.release = None
    assert (await manager.invoke(request())).success is True


async def test_concurrency_limit_serializes_calls() -> None:
    manager, provider = await build_runtime(limit=1)
    provider.release = asyncio.Event()
    first = asyncio.create_task(manager.invoke(request(timeout_ms=1000)))
    await provider.entered.wait()
    second = asyncio.create_task(manager.invoke(request(timeout_ms=1000)))
    await asyncio.sleep(0)
    assert provider.max_active == 1
    provider.release.set()
    await asyncio.gather(first, second)
    assert provider.active == 0


async def test_unavailable_and_unsupported_requests_are_rejected() -> None:
    manager, _ = await build_runtime()
    with pytest.raises(CapabilityNotSupportedError):
        await manager.invoke(request(capability=OTHER))
    unavailable, _ = await build_runtime(initialize=False)
    with pytest.raises(ProviderUnavailableError):
        await unavailable.invoke(request())
    with pytest.raises(ValueError, match="positive"):
        await build_runtime(limit=0)
