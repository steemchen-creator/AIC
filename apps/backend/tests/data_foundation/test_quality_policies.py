from datetime import UTC, datetime, timedelta

import pytest

from aic_backend.data_foundation.quality import (
    CompletenessPolicy,
    DataQualityFlag,
    FreshnessPolicy,
    SourceClassification,
)
from aic_backend.data_foundation.quality.policies import (
    assess_completeness,
    assess_freshness,
    assess_source_confidence,
)

NOW = datetime(2026, 1, 8, tzinfo=UTC)


def test_daily_bar_freshness_fresh_middle_stale_and_thresholds() -> None:
    policy = FreshnessPolicy(timedelta(days=1), timedelta(days=7))
    assert assess_freshness(NOW, NOW, policy).score == 100.0
    assert assess_freshness(NOW - timedelta(days=1), NOW, policy).score == 100.0
    assert assess_freshness(NOW - timedelta(days=4), NOW, policy).score == 50.0
    stale = assess_freshness(NOW - timedelta(days=7), NOW, policy)
    assert stale.score == 0.0
    assert stale.flags == (DataQualityFlag.STALE,)


def test_freshness_rejects_naive_and_future_time_without_system_clock() -> None:
    policy = FreshnessPolicy()
    with pytest.raises(ValueError, match="event_time"):
        assess_freshness(datetime(2026, 1, 1), NOW, policy)
    with pytest.raises(ValueError, match="reference_time"):
        assess_freshness(NOW, datetime(2026, 1, 8), policy)
    with pytest.raises(ValueError, match="after"):
        assess_freshness(NOW + timedelta(microseconds=1), NOW, policy)


def test_completeness_present_missing_unavailable_and_incomplete() -> None:
    policy = CompletenessPolicy(("turnover", "settlement_price"), 40.0)
    complete = assess_completeness(
        {"turnover": 1, "settlement_price": 1}, policy, frozenset()
    )
    one_missing = assess_completeness({"turnover": 1}, policy, frozenset())
    unavailable = assess_completeness(
        {"turnover": 1}, policy, frozenset({"settlement_price"})
    )
    incomplete = assess_completeness({}, policy, frozenset())
    no_expected = assess_completeness(
        {}, policy, frozenset({"turnover", "settlement_price"})
    )

    assert complete.score == 100.0 and complete.flags == ()
    assert one_missing.score == 50.0
    assert one_missing.flags == (DataQualityFlag.MISSING_OPTIONAL_FIELD,)
    assert unavailable.score == 100.0 and unavailable.flags == ()
    assert incomplete.score == 0.0
    assert incomplete.flags == (DataQualityFlag.INCOMPLETE,)
    assert no_expected.score == 100.0


@pytest.mark.parametrize(
    ("classification", "expected"),
    [
        (SourceClassification.OFFICIAL_EXCHANGE, 100.0),
        (SourceClassification.LICENSED_VENDOR, 90.0),
        (SourceClassification.PUBLIC_FINANCIAL_API, 70.0),
        (SourceClassification.DERIVED_SOURCE, 50.0),
        (SourceClassification.UNKNOWN, 30.0),
        ("UNRECOGNIZED", 30.0),
    ],
)
def test_source_confidence_mapping_is_deterministic_and_safe(
    classification: object, expected: float
) -> None:
    assert assess_source_confidence(classification).score == expected
