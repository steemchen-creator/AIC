from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from aic_backend.provider_runtime import (
    CapabilityMode,
    HealthCheckResult,
    HealthStatus,
    InvocationRecord,
    ProviderAttribution,
    ProviderCapability,
    ProviderEventType,
    ProviderInvocationRequest,
    ProviderInvocationResponse,
    ProviderMetadata,
    ProviderRequestContext,
    ProviderRuntimeEvent,
    ProviderSnapshot,
    ProviderStatus,
    ProviderType,
    SelectionDecision,
)

NOW = datetime(2026, 7, 29, tzinfo=UTC)
CAPABILITY = ProviderCapability(
    name="market.quote.snapshot",
    version="1.0.0",
    mode=CapabilityMode.SNAPSHOT,
)


def metadata(**overrides: object) -> ProviderMetadata:
    values: dict[str, object] = {
        "provider_id": "mock_market_primary",
        "display_name": "Mock Market Primary",
        "provider_type": ProviderType.MOCK,
        "version": "1.0.0",
        "priority": 100,
    }
    values.update(overrides)
    return ProviderMetadata(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "provider_id",
    ["", "AB", "2mock", "mock-market", "中文", "a" * 65],
)
def test_metadata_rejects_invalid_provider_id(provider_id: str) -> None:
    with pytest.raises(ValueError, match="provider_id"):
        metadata(provider_id=provider_id)


@pytest.mark.parametrize("version", ["1", "1.0", "01.0.0", "latest"])
def test_metadata_rejects_invalid_semantic_version(version: str) -> None:
    with pytest.raises(ValueError, match="semantic version"):
        metadata(version=version)


def test_metadata_is_frozen_and_validates_priority() -> None:
    value = metadata(tags=frozenset({"deterministic"}))

    with pytest.raises(FrozenInstanceError):
        value.priority = 200  # type: ignore[misc]
    with pytest.raises(ValueError, match="priority"):
        metadata(priority=1001)
    with pytest.raises(ValueError, match="tags"):
        metadata(tags=frozenset({""}))


@pytest.mark.parametrize(
    "name", ["stock_data", "market.quote", "Market.quote.snapshot", "market..snapshot"]
)
def test_capability_rejects_ambiguous_or_invalid_name(name: str) -> None:
    with pytest.raises(ValueError, match="capability name"):
        ProviderCapability(name=name, version="1.0.0", mode=CapabilityMode.SNAPSHOT)


def test_health_result_requires_timezone_and_freezes_details() -> None:
    details = {"region": "test"}
    result = HealthCheckResult(
        status=HealthStatus.HEALTHY,
        checked_at=NOW,
        latency_ms=1.5,
        details=details,
    )
    details["region"] = "changed"

    assert result.details == {"region": "test"}
    with pytest.raises(TypeError):
        result.details["region"] = "changed"  # type: ignore[index]
    with pytest.raises(ValueError, match="timezone"):
        HealthCheckResult(status=HealthStatus.UNKNOWN, checked_at=datetime(2026, 7, 29))
    with pytest.raises(ValueError, match="latency_ms"):
        HealthCheckResult(status=HealthStatus.UNHEALTHY, checked_at=NOW, latency_ms=-0.1)


def test_snapshot_validates_score_counts_and_time() -> None:
    with pytest.raises(ValueError, match="quality_score"):
        ProviderSnapshot(
            metadata=metadata(),
            capabilities=frozenset({CAPABILITY}),
            lifecycle_status=ProviderStatus.READY,
            health=None,
            quality_score=100.1,
            in_flight_requests=0,
            registered_at=NOW,
            last_state_change_at=NOW,
        )


def test_request_context_requires_request_id_and_positive_timeout() -> None:
    with pytest.raises(ValueError, match="request_id"):
        ProviderRequestContext(capability=CAPABILITY, request_id=" ", timeout_ms=100)
    with pytest.raises(ValueError, match="timeout_ms"):
        ProviderRequestContext(capability=CAPABILITY, request_id="req_1", timeout_ms=0)


def test_invocation_request_and_result_copy_payloads() -> None:
    request_payload = {"symbol": "TEST"}
    result_payload = {"price": 42}
    request = ProviderInvocationRequest(
        request_id="req_1",
        provider_id="mock_market_primary",
        capability=CAPABILITY,
        payload=request_payload,
        timeout_ms=100,
        created_at=NOW,
    )
    result = ProviderInvocationResponse(payload=result_payload, source_timestamp=NOW)
    request_payload["symbol"] = "CHANGED"
    result_payload["price"] = 0

    assert request.payload == {"symbol": "TEST"}
    assert result.payload == {"price": 42}


def test_attribution_validates_time_and_failover_count() -> None:
    with pytest.raises(ValueError, match="failover_count"):
        ProviderAttribution(
            provider_id="mock_market_primary",
            capability=CAPABILITY.name,
            invocation_id="inv_1",
            retrieved_at=NOW,
            source_timestamp=None,
            failover_count=-1,
        )


def test_invocation_record_validates_audit_fields() -> None:
    record = InvocationRecord(
        invocation_id="inv_1",
        request_id="req_1",
        provider_id="mock_market_primary",
        capability=CAPABILITY.name,
        attempt=1,
        started_at=NOW,
        finished_at=NOW,
        duration_ms=0,
        outcome="success",
    )

    assert record.error_code is None
    with pytest.raises(ValueError, match="attempt"):
        InvocationRecord(
            invocation_id="inv_1",
            request_id="req_1",
            provider_id="mock_market_primary",
            capability=CAPABILITY.name,
            attempt=0,
            started_at=NOW,
            finished_at=NOW,
            duration_ms=0,
            outcome="failed",
        )


def test_selection_decision_copies_explanation_mappings() -> None:
    scores = {"mock_market_primary": 98.4}
    from aic_backend.provider_runtime import (
        ProviderExclusionReason,
        ProviderSelectionReason,
        QualityScoreBreakdown,
    )

    breakdown = QualityScoreBreakdown(98.4, 100, 100, 100, 84, 100, False, False, False, False)
    decision = SelectionDecision(
        request_id="req_1",
        capability=CAPABILITY,
        selected_provider_id="mock_market_primary",
        ordered_candidate_provider_ids=("mock_market_primary",),
        candidate_scores=scores,
        score_breakdowns={"mock_market_primary": breakdown},
        selection_reasons={"mock_market_primary": (ProviderSelectionReason.READY_STATE,)},
        excluded_providers={"mock_disabled": ProviderExclusionReason.PROVIDER_DISABLED},
        decided_at=NOW,
    )
    scores["mock_market_primary"] = 0

    assert decision.candidate_scores["mock_market_primary"] == 98.4


def test_provider_runtime_event_is_validated_and_immutable() -> None:
    payload = {"provider_id": "mock_market_primary"}
    event = ProviderRuntimeEvent(
        event_id="evt_1",
        event_type=ProviderEventType.REGISTERED,
        occurred_at=NOW,
        payload=payload,
    )
    payload["provider_id"] = "changed"

    assert event.event_type == "provider_registered"
    assert event.payload == {"provider_id": "mock_market_primary"}
    with pytest.raises(ValueError, match="event_id"):
        ProviderRuntimeEvent(
            event_id="",
            event_type=ProviderEventType.READY,
            occurred_at=NOW,
            payload={},
        )
