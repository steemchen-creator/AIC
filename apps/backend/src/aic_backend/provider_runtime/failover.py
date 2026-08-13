"""Bounded, explainable failover across distinct Providers."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from aic_backend.provider_runtime.errors import (
    FailoverExhaustedError,
    FailoverNotAllowedError,
    ProviderExecutionError,
    ProviderInvocationError,
    ProviderSelectionError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from aic_backend.provider_runtime.interfaces import ProviderInvoker
from aic_backend.provider_runtime.models import (
    FailoverAttempt,
    FailoverContext,
    FailoverDecision,
    ProviderInvocationRequest,
    ProviderInvocationResult,
    ProviderMetricsSnapshot,
    ProviderRegistrySnapshot,
    ProviderRequestContext,
)
from aic_backend.provider_runtime.selector import ProviderSelector


class FailoverPolicy:
    """Pure allowlist policy for Provider-switching errors."""

    _ALLOWED = (ProviderTimeoutError, ProviderExecutionError, ProviderUnavailableError)

    def decide(
        self,
        context: FailoverContext,
        error: ProviderInvocationError,
        next_provider_candidates: tuple[str, ...],
    ) -> FailoverDecision:
        allowed = isinstance(error, self._ALLOWED)
        return FailoverDecision(
            should_failover=allowed,
            reason=(
                f"{error.error_code} permits provider failover."
                if allowed
                else f"{error.error_code} does not permit provider failover."
            ),
            excluded_provider_ids=frozenset(context.attempted_provider_ids),
            next_provider_candidates=next_provider_candidates if allowed else (),
            attempt_number=len(context.attempted_provider_ids),
        )


class ProviderFailoverManager:
    """Select and invoke distinct Providers within an explicit failover budget."""

    def __init__(
        self,
        selector: ProviderSelector,
        invocation: ProviderInvoker,
        policy: FailoverPolicy,
    ) -> None:
        self._selector = selector
        self._invocation = invocation
        self._policy = policy

    async def execute(
        self,
        context: ProviderRequestContext,
        payload: Mapping[str, Any],
        registry_snapshot: ProviderRegistrySnapshot,
        metrics: Mapping[str, ProviderMetricsSnapshot],
        now: datetime,
        *,
        max_failover_attempts: int = 1,
    ) -> ProviderInvocationResult:
        if max_failover_attempts < 0:
            raise ValueError("max_failover_attempts must not be negative")
        selection = self._selector.select(context, registry_snapshot, metrics, now)
        original_provider_id = selection.selected_provider_id
        attempted: list[str] = []
        history: list[FailoverAttempt] = []
        provider_id = original_provider_id
        last_error: ProviderInvocationError | None = None

        while True:
            attempted.append(provider_id)
            request = ProviderInvocationRequest(
                request_id=context.request_id,
                provider_id=provider_id,
                capability=context.capability,
                payload=payload,
                timeout_ms=context.timeout_ms,
                created_at=now,
            )
            try:
                result = await self._invocation.invoke(request)
            except ProviderInvocationError as error:
                last_error = error
                history.append(
                    FailoverAttempt(provider_id, len(history) + 1, False, error.error_code)
                )
                failover_context = FailoverContext(
                    request_id=context.request_id,
                    capability=context.capability,
                    original_provider_id=original_provider_id,
                    attempted_provider_ids=tuple(attempted),
                    max_failover_attempts=max_failover_attempts,
                    started_at=now,
                )
                remaining = tuple(
                    candidate
                    for candidate in selection.ordered_candidate_provider_ids
                    if candidate not in attempted
                )
                decision = self._policy.decide(failover_context, error, remaining)
                if not decision.should_failover:
                    raise FailoverNotAllowedError(
                        "Provider failure is not eligible for failover.",
                        request_id=context.request_id,
                        capability=context.capability.name,
                        attempted_provider_ids=tuple(attempted),
                        last_error=error,
                    ) from error
                if len(attempted) - 1 >= max_failover_attempts:
                    break
                failover_selection_context = replace(
                    context,
                    excluded_provider_ids=context.excluded_provider_ids.union(attempted),
                )
                try:
                    selection = self._selector.select(
                        failover_selection_context, registry_snapshot, metrics, now
                    )
                except ProviderSelectionError:
                    break
                provider_id = selection.selected_provider_id
                continue
            history.append(FailoverAttempt(provider_id, len(history) + 1, True))
            return replace(
                result,
                attempt_history=tuple(history),
                failover_count=len(history) - 1,
            )

        assert last_error is not None
        raise FailoverExhaustedError(
            "Provider failover attempts were exhausted.",
            request_id=context.request_id,
            capability=context.capability.name,
            attempted_provider_ids=tuple(attempted),
            last_error=last_error,
        ) from last_error
