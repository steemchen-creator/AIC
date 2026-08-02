"""Pure Provider filtering and deterministic candidate ordering."""

from collections.abc import Mapping
from datetime import datetime

from aic_backend.provider_runtime.errors import (
    CapabilityUnavailableError,
    NoProviderAvailableError,
)
from aic_backend.provider_runtime.models import (
    HealthStatus,
    ProviderCandidate,
    ProviderExclusionReason,
    ProviderMetricsSnapshot,
    ProviderRegistrySnapshot,
    ProviderRequestContext,
    ProviderSelectionReason,
    ProviderSnapshot,
    ProviderStatus,
    SelectionDecision,
)
from aic_backend.provider_runtime.scoring import QualityScorer


class ProviderSelector:
    def __init__(self, scorer: QualityScorer) -> None:
        self._scorer = scorer

    def select(
        self,
        context: ProviderRequestContext,
        registry_snapshot: ProviderRegistrySnapshot,
        metrics: Mapping[str, ProviderMetricsSnapshot],
        now: datetime,
    ) -> SelectionDecision:
        supported = [
            provider
            for provider in registry_snapshot.providers
            if context.capability in provider.capabilities
        ]
        if not supported:
            raise CapabilityUnavailableError(
                "No registered Provider supports the requested capability.",
                request_id=context.request_id,
                capability=context.capability.name,
                supported_provider_count=0,
            )

        preferred_ranks = {
            provider_id: rank
            for rank, provider_id in enumerate(context.preferred_provider_ids)
        }
        candidates: list[ProviderCandidate] = []
        excluded: dict[str, ProviderExclusionReason] = {}
        for provider in sorted(
            registry_snapshot.providers, key=lambda item: item.metadata.provider_id
        ):
            provider_id = provider.metadata.provider_id
            reason = self._exclusion_reason(
                provider, context, metrics.get(provider_id), now
            )
            if reason is not None:
                excluded[provider.metadata.provider_id] = reason
                continue
            provider_metrics = metrics.get(provider_id) or ProviderMetricsSnapshot(
                provider_id=provider_id,
                in_flight_requests=provider.in_flight_requests,
            )
            breakdown = self._scorer.score(provider, provider_metrics, now)
            candidates.append(
                ProviderCandidate(
                    provider_id=provider_id,
                    lifecycle_status=provider.lifecycle_status,
                    health_status=(
                        provider.health.status if provider.health else HealthStatus.UNKNOWN
                    ),
                    priority=provider.metadata.priority,
                    quality_score=breakdown.total_score,
                    score_breakdown=breakdown,
                    preferred_rank=preferred_ranks.get(provider.metadata.provider_id),
                )
            )
        if not candidates:
            raise NoProviderAvailableError(
                f"{len(supported)} Provider(s) support the capability but none are available; "
                + ", ".join(f"{key}:{value.value}" for key, value in sorted(excluded.items())),
                request_id=context.request_id,
                capability=context.capability.name,
                supported_provider_count=len(supported),
                exclusion_summary={key: value.value for key, value in excluded.items()},
            )
        candidates.sort(key=self._sort_key)
        ids = tuple(candidate.provider_id for candidate in candidates)
        return SelectionDecision(
            request_id=context.request_id,
            capability=context.capability,
            selected_provider_id=ids[0],
            ordered_candidate_provider_ids=ids,
            candidate_scores={item.provider_id: item.quality_score for item in candidates},
            score_breakdowns={item.provider_id: item.score_breakdown for item in candidates},
            selection_reasons={item.provider_id: self._reasons(item) for item in candidates},
            excluded_providers=excluded,
            decided_at=now,
        )

    @staticmethod
    def _exclusion_reason(
        provider: ProviderSnapshot,
        context: ProviderRequestContext,
        metrics: ProviderMetricsSnapshot | None,
        now: datetime,
    ) -> ProviderExclusionReason | None:
        if not provider.metadata.enabled:
            return ProviderExclusionReason.PROVIDER_DISABLED
        if context.capability not in provider.capabilities:
            return ProviderExclusionReason.CAPABILITY_NOT_SUPPORTED
        if provider.metadata.provider_id in context.excluded_provider_ids:
            return ProviderExclusionReason.EXPLICITLY_EXCLUDED
        if provider.lifecycle_status is ProviderStatus.DEGRADED and not context.allow_degraded:
            return ProviderExclusionReason.DEGRADED_NOT_ALLOWED
        if provider.lifecycle_status not in {ProviderStatus.READY, ProviderStatus.DEGRADED}:
            return ProviderExclusionReason.LIFECYCLE_NOT_SELECTABLE
        health = provider.health.status if provider.health else HealthStatus.UNKNOWN
        if health is HealthStatus.UNHEALTHY:
            return ProviderExclusionReason.HEALTH_UNHEALTHY
        if health is HealthStatus.UNKNOWN:
            return ProviderExclusionReason.HEALTH_UNKNOWN
        if (
            metrics is not None
            and metrics.cooldown_until is not None
            and metrics.cooldown_until > now
        ):
            return ProviderExclusionReason.PROVIDER_IN_COOLDOWN
        in_flight = metrics.in_flight_requests if metrics else provider.in_flight_requests
        max_concurrency = metrics.max_concurrency if metrics else 1
        if in_flight >= max_concurrency:
            return ProviderExclusionReason.CONCURRENCY_CAPACITY_EXHAUSTED
        return None

    @staticmethod
    def _sort_key(candidate: ProviderCandidate) -> tuple[int, int, int, float, int, str]:
        return (
            0 if candidate.preferred_rank is not None else 1,
            candidate.preferred_rank if candidate.preferred_rank is not None else 0,
            0 if candidate.lifecycle_status is ProviderStatus.READY else 1,
            -candidate.quality_score,
            -candidate.priority,
            candidate.provider_id,
        )

    @staticmethod
    def _reasons(candidate: ProviderCandidate) -> tuple[ProviderSelectionReason, ...]:
        reasons = []
        if candidate.preferred_rank is not None:
            reasons.append(ProviderSelectionReason.PREFERRED_PROVIDER)
        reasons.append(
            ProviderSelectionReason.READY_STATE
            if candidate.lifecycle_status is ProviderStatus.READY
            else ProviderSelectionReason.DEGRADED_STATE
        )
        reasons.extend(
            (
                ProviderSelectionReason.HIGHER_QUALITY_SCORE,
                ProviderSelectionReason.HIGHER_PRIORITY,
                ProviderSelectionReason.STABLE_PROVIDER_ID_TIE_BREAK,
            )
        )
        return tuple(reasons)
