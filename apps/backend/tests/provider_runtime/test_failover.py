from datetime import UTC, datetime

import pytest

from aic_backend.provider_runtime import (
    CapabilityMode,
    FailoverContext,
    FailoverPolicy,
    HealthCheckResult,
    HealthStatus,
    ProviderCapability,
    ProviderFailoverManager,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderMetadata,
    ProviderRegistrySnapshot,
    ProviderRequestContext,
    ProviderSelector,
    ProviderSnapshot,
    ProviderStatus,
    ProviderType,
    QualityScorer,
)
from aic_backend.provider_runtime.errors import (
    CapabilityNotSupportedError,
    FailoverExhaustedError,
    FailoverNotAllowedError,
    InvalidRequestError,
    ProviderExecutionError,
    ProviderInvalidResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

NOW = datetime(2026, 8, 11, tzinfo=UTC)
CAPABILITY = ProviderCapability("market.quote.snapshot", "1.0.0", CapabilityMode.SNAPSHOT)


def snapshot(provider_id: str, priority: int) -> ProviderSnapshot:
    return ProviderSnapshot(
        ProviderMetadata(
            provider_id, provider_id, ProviderType.MOCK, "1.0.0", priority=priority
        ),
        frozenset({CAPABILITY}),
        ProviderStatus.READY,
        HealthCheckResult(HealthStatus.HEALTHY, NOW),
        None,
        0,
        NOW,
        NOW,
    )


def request_context() -> ProviderRequestContext:
    return ProviderRequestContext("req_1", CAPABILITY, 100)


def success(request: ProviderInvocationRequest) -> ProviderInvocationResult:
    return ProviderInvocationResult(
        request.request_id,
        request.provider_id,
        True,
        {"provider": request.provider_id},
        None,
        1,
        NOW,
        NOW,
    )


class FakeInvoker:
    def __init__(self, failures: dict[str, Exception]) -> None:
        self.failures = failures
        self.calls: list[str] = []

    async def invoke(self, request: ProviderInvocationRequest) -> ProviderInvocationResult:
        self.calls.append(request.provider_id)
        error = self.failures.get(request.provider_id)
        if error is not None:
            raise error
        return success(request)


def runtime(
    failures: dict[str, Exception], provider_count: int = 3
) -> tuple[ProviderFailoverManager, FakeInvoker, ProviderRegistrySnapshot]:
    invoker = FakeInvoker(failures)
    manager = ProviderFailoverManager(
        ProviderSelector(QualityScorer()), invoker, FailoverPolicy()
    )
    providers = tuple(
        snapshot(f"mock_{letter}", provider_count - index)
        for index, letter in enumerate(("a", "b", "c")[:provider_count])
    )
    return manager, invoker, ProviderRegistrySnapshot(providers, NOW)


def error(error_type, provider_id: str = "mock_a"):
    return error_type(
        "safe failure",
        request_id="req_1",
        provider_id=provider_id,
        capability=CAPABILITY.name,
    )


@pytest.mark.parametrize(
    "failure",
    [
        error(ProviderTimeoutError),
        error(ProviderExecutionError),
        error(ProviderUnavailableError),
    ],
)
def test_policy_allows_only_transient_provider_failures(failure) -> None:
    context = FailoverContext("req_1", CAPABILITY, "mock_a", ("mock_a",), 1, NOW)
    decision = FailoverPolicy().decide(context, failure, ("mock_b",))
    assert decision.should_failover is True
    assert decision.next_provider_candidates == ("mock_b",)
    assert decision.excluded_provider_ids == frozenset({"mock_a"})


@pytest.mark.parametrize(
    "failure",
    [
        error(InvalidRequestError),
        error(CapabilityNotSupportedError),
        error(ProviderInvalidResponseError),
    ],
)
def test_policy_rejects_request_capability_and_protocol_failures(failure) -> None:
    context = FailoverContext("req_1", CAPABILITY, "mock_a", ("mock_a",), 1, NOW)
    assert FailoverPolicy().decide(context, failure, ("mock_b",)).should_failover is False


async def test_a_fails_b_succeeds_with_attribution_history() -> None:
    manager, invoker, registry = runtime({"mock_a": error(ProviderTimeoutError)})
    result = await manager.execute(request_context(), {}, registry, {}, NOW)
    assert invoker.calls == ["mock_a", "mock_b"]
    assert result.provider_id == "mock_b"
    assert result.failover_count == 1
    assert tuple(item.provider_id for item in result.attempt_history) == (
        "mock_a",
        "mock_b",
    )
    assert result.attempt_history[0].error_code == "PROVIDER_TIMEOUT"


async def test_a_and_b_fail_then_exhaust_without_repeating_provider() -> None:
    failures = {
        "mock_a": error(ProviderExecutionError, "mock_a"),
        "mock_b": error(ProviderUnavailableError, "mock_b"),
    }
    manager, invoker, registry = runtime(failures)
    with pytest.raises(FailoverExhaustedError) as raised:
        await manager.execute(
            request_context(), {}, registry, {}, NOW, max_failover_attempts=1
        )
    assert invoker.calls == ["mock_a", "mock_b"]
    assert raised.value.attempted_provider_ids == ("mock_a", "mock_b")
    assert raised.value.last_error.error_code == "PROVIDER_UNAVAILABLE"


async def test_zero_failover_budget_stops_after_original_provider() -> None:
    manager, invoker, registry = runtime({"mock_a": error(ProviderTimeoutError)})
    with pytest.raises(FailoverExhaustedError):
        await manager.execute(
            request_context(), {}, registry, {}, NOW, max_failover_attempts=0
        )
    assert invoker.calls == ["mock_a"]


async def test_negative_budget_is_rejected_before_invocation() -> None:
    manager, invoker, registry = runtime({})
    with pytest.raises(ValueError, match="negative"):
        await manager.execute(
            request_context(), {}, registry, {}, NOW, max_failover_attempts=-1
        )
    assert invoker.calls == []


async def test_no_backup_candidate_becomes_exhausted() -> None:
    manager, invoker, registry = runtime(
        {"mock_a": error(ProviderTimeoutError)}, provider_count=1
    )
    with pytest.raises(FailoverExhaustedError):
        await manager.execute(request_context(), {}, registry, {}, NOW)
    assert invoker.calls == ["mock_a"]


async def test_noneligible_error_is_not_hidden_or_switched() -> None:
    failure = error(InvalidRequestError)
    manager, invoker, registry = runtime({"mock_a": failure})
    with pytest.raises(FailoverNotAllowedError) as raised:
        await manager.execute(request_context(), {}, registry, {}, NOW)
    assert invoker.calls == ["mock_a"]
    assert raised.value.last_error is failure
    assert "secret" not in str(raised.value)


async def test_three_distinct_providers_respect_two_failover_budget() -> None:
    failures = {
        "mock_a": error(ProviderTimeoutError, "mock_a"),
        "mock_b": error(ProviderExecutionError, "mock_b"),
    }
    manager, invoker, registry = runtime(failures)
    result = await manager.execute(
        request_context(), {}, registry, {}, NOW, max_failover_attempts=2
    )
    assert invoker.calls == ["mock_a", "mock_b", "mock_c"]
    assert len(set(invoker.calls)) == 3
    assert result.provider_id == "mock_c"
    assert result.failover_count == 2


def test_failover_context_rejects_duplicates_and_invalid_budget() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        FailoverContext("req_1", CAPABILITY, "mock_a", ("mock_a", "mock_a"), 1, NOW)
    with pytest.raises(ValueError, match="negative"):
        FailoverContext("req_1", CAPABILITY, "mock_a", (), -1, NOW)
