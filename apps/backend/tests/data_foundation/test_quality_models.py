from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from aic_backend.data_foundation.quality import (
    CompletenessPolicy,
    ConflictValue,
    DataConflict,
    DataQualityAssessment,
    DataQualityFlag,
    FreshnessPolicy,
    QualityContext,
)


def test_quality_assessment_clamps_rounds_deduplicates_and_sorts() -> None:
    value = DataQualityAssessment(
        score=101.999,
        freshness_score=-1,
        completeness_score=33.336,
        consistency_score=100.004,
        source_confidence_score=70.005,
        flags=(DataQualityFlag.STALE, DataQualityFlag.INCOMPLETE, DataQualityFlag.STALE),
    )
    assert value.score == 100.0
    assert value.freshness_score == 0.0
    assert value.completeness_score == 33.34
    assert value.consistency_score == 100.0
    assert value.source_confidence_score == 70.0
    assert value.flags == (DataQualityFlag.INCOMPLETE, DataQualityFlag.STALE)
    with pytest.raises(FrozenInstanceError):
        value.score = 0  # type: ignore[misc]


def test_quality_context_is_immutable_sorted_and_validated() -> None:
    values = (
        ConflictValue("provider-b", Decimal("10.2")),
        ConflictValue("provider-a", Decimal("10.1")),
    )
    conflict_b = DataConflict("rec-2", "close", values)
    conflict_a = DataConflict("rec-1", "open", values)
    context = QualityContext(conflicts=(conflict_b, conflict_a))
    assert tuple(item.record_identity for item in context.conflicts) == ("rec-1", "rec-2")
    assert tuple(item.provider_id for item in conflict_a.values) == (
        "provider-a",
        "provider-b",
    )
    with pytest.raises(ValueError, match="unavailable"):
        QualityContext(unavailable_fields=frozenset({""}))


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: ConflictValue("", Decimal("1")),
        lambda: ConflictValue("provider", 1.0),
        lambda: ConflictValue("provider", Decimal("1"), datetime(2026, 1, 1)),
        lambda: DataConflict("", "close", (ConflictValue("a", Decimal("1")),) * 2),
        lambda: DataConflict("rec", "", (ConflictValue("a", Decimal("1")),) * 2),
        lambda: DataConflict("rec", "close", (ConflictValue("a", Decimal("1")),)),
    ],
)
def test_conflict_models_reject_invalid_values(constructor: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        constructor()  # type: ignore[operator]


def test_policy_configuration_is_centralized_and_validated() -> None:
    assert FreshnessPolicy().fresh_threshold == timedelta(days=1)
    assert FreshnessPolicy().stale_threshold == timedelta(days=7)
    with pytest.raises(ValueError):
        FreshnessPolicy(timedelta(seconds=-1), timedelta(days=1))
    with pytest.raises(ValueError):
        FreshnessPolicy(timedelta(days=1), timedelta(days=1))
    with pytest.raises(ValueError):
        CompletenessPolicy(("turnover", "turnover"))
    policy = CompletenessPolicy(("turnover",), 150)
    assert policy.incomplete_threshold == 100.0
