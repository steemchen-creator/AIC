from datetime import UTC, datetime
from decimal import Decimal

from aic_backend.data_foundation.quality import (
    ConflictDetector,
    ConflictValue,
    DataQualityFlag,
)
from aic_backend.data_foundation.quality.policies import assess_consistency


def values(a: str, b: str) -> tuple[ConflictValue, ...]:
    observed = datetime(2026, 1, 2, tzinfo=UTC)
    return (
        ConflictValue("provider-a", Decimal(a), observed),
        ConflictValue("provider-b", Decimal(b), observed),
    )


def test_same_decimal_value_is_not_a_conflict() -> None:
    assert ConflictDetector().detect("rec-1", "close", values("10.210", "10.210")) is None


def test_exact_decimal_difference_is_represented_without_winner_or_average() -> None:
    conflict = ConflictDetector().detect("rec-1", "close", values("10.21", "10.2101"))
    assert conflict is not None
    assert tuple(item.value for item in conflict.values) == (
        Decimal("10.21"),
        Decimal("10.2101"),
    )
    assert not hasattr(conflict, "winner")
    assert not hasattr(conflict, "average")


def test_consistency_counts_affected_fields_once_and_is_deterministic() -> None:
    detector = ConflictDetector()
    close = detector.detect("rec-1", "close", values("10.21", "10.24"))
    high = detector.detect("rec-1", "high", values("10.5", "10.6"))
    assert close is not None and high is not None
    comparable = frozenset({"open", "high", "low", "close"})
    no_conflict = assess_consistency((), comparable)
    one = assess_consistency((close,), comparable)
    two = assess_consistency((close, high), comparable)

    assert no_conflict.score == 100.0 and no_conflict.flags == ()
    assert one.score == 75.0
    assert two.score == 50.0
    assert two.flags == (DataQualityFlag.CONFLICTING_SOURCE,)
    assert assess_consistency((close, high), comparable) == two
