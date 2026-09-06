from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from aic_backend.domain.experiments import (
    AssetClass,
    AssetUniverse,
    ComparisonPolicy,
    ComparisonSampleStatus,
    Currency,
    DecisionSourceAssignment,
    DecisionSourceKind,
    ExperimentManifest,
    ExperimentMember,
    ExperimentMemberDefinition,
    ExperimentPolicyBundle,
    FairnessContract,
    GroupSessionStatus,
    GroupTradingSession,
    InvestmentHorizon,
    ManagerProfile,
    MarketVenue,
    MemberSessionResult,
    MemberSessionStatus,
    PortfolioRole,
    RoleActivity,
    RoleActivityStatus,
    RoleIdentity,
    TradingStyle,
    build_comparison_snapshot,
    latest_role_activity,
)
from aic_backend.domain.paper import MetricSampleStatus, PaperPerformanceSnapshot
from aic_backend.domain.portfolio.models import Money, PortfolioId

NOW = datetime(2026, 9, 6, 8, tzinfo=UTC)
DAY = date(2026, 9, 7)


def policy() -> ExperimentPolicyBundle:
    return ExperimentPolicyBundle(
        "pit-operational-replay/v1",
        "a-share-calendar/v1",
        "next-session-open/v1",
        "a-share-pre-trade-risk/v1",
        "a-share-fees/v1",
        "fixed-bps/v1",
        "CN.SSE.000001",
        Money(Decimal("500000")),
        DAY,
        "shadow-experiment/v1",
        "shadow-comparison/v1",
        AssetUniverse(
            (AssetClass.EQUITY, AssetClass.ETF, AssetClass.CASH),
            (MarketVenue.CN_SSE, MarketVenue.CN_SZSE),
            (Currency.CNY,),
            Currency.CNY,
        ),
    )


def definition(role: RoleIdentity, portfolio_role: PortfolioRole) -> ExperimentMemberDefinition:
    return ExperimentMemberDefinition(
        portfolio_role,
        ManagerProfile(
            f"manager-{role.value.lower()}",
            role.value.title(),
            f"{role.value.title()} Portfolio Manager",
            f"Mandate for {role.value}",
            f"avatars/{role.value.lower()}.svg",
            role,
            True,
            (InvestmentHorizon.MEDIUM,),
            (TradingStyle.TREND,),
        ),
        DecisionSourceAssignment(
            f"fixture/{role.value.lower()}",
            DecisionSourceKind.FIXTURE,
            "v1",
            f"fixtures/{role.value.lower()}.json",
        ),
    )


def manifest(bundle: ExperimentPolicyBundle | None = None) -> ExperimentManifest:
    actual = bundle or policy()
    roles = (
        (RoleIdentity.CHAMPION, PortfolioRole.CHAMPION),
        (RoleIdentity.ATLAS, PortfolioRole.SHADOW),
        (RoleIdentity.SAGE, PortfolioRole.SHADOW),
        (RoleIdentity.AEGIS, PortfolioRole.SHADOW),
    )
    members = tuple(
        ExperimentMember(
            f"account-{role.value.lower()}",
            PortfolioId(f"portfolio-{role.value.lower()}"),
            definition(role, portfolio_role),
            actual.identity,
            actual.initial_capital,
        )
        for role, portfolio_role in roles
    )
    contract = FairnessContract(
        "fairness-1",
        actual.identity,
        actual.initial_capital,
        tuple(item.account_id for item in members),
        tuple(sorted(FairnessContract.REQUIRED_DIMENSIONS)),
        NOW,
    )
    return ExperimentManifest(
        "experiment-1", "Foundation Lab", actual, members, contract, NOW
    )


def performance(account_id: str, total_return: str, costs: str) -> PaperPerformanceSnapshot:
    capital = Decimal("500000")
    return_value = Decimal(total_return)
    nav = capital * (Decimal("1") + return_value)
    return PaperPerformanceSnapshot(
        f"snapshot-{account_id}",
        account_id,
        f"session-{account_id}",
        DAY,
        NOW,
        Money(Decimal("400000")),
        Money(nav - Decimal("400000")),
        Money(Decimal("0")),
        Money(nav - capital),
        Money(nav),
        Money(nav - capital + Decimal(costs)),
        Money(nav - capital),
        Money(nav - Decimal("400000")),
        Decimal("400000") / nav,
        Decimal("0.2"),
        1,
        Decimal("3100"),
        return_value,
        return_value,
        Money(max(nav, capital)),
        Decimal("-0.01"),
        Decimal("-0.02"),
        return_value,
        None,
        Decimal("0.1") + return_value,
        Decimal("0.08") + return_value,
        Decimal("1.0") + return_value,
        Decimal("2.0") + return_value,
        Decimal("0.01"),
        return_value - Decimal("0.01"),
        Decimal("0.05"),
        Money(Decimal(costs)),
        Money(Decimal("0")),
        Money(Decimal("0")),
        1,
        MetricSampleStatus.SUFFICIENT,
        "paper-performance/v1",
        (),
    )


def group_session(value: ExperimentManifest) -> GroupTradingSession:
    results = tuple(
        MemberSessionResult(
            member.account_id,
            member.definition.decision_source.source_id,
            MemberSessionStatus.SUCCEEDED,
            f"paper-session-{member.account_id}",
            f"snapshot-{member.account_id}",
        )
        for member in value.members
    )
    return GroupTradingSession(
        "group-session-1",
        value.group_id,
        DAY,
        NOW,
        NOW,
        NOW,
        GroupSessionStatus.FINALIZED,
        results,
        value.policy_bundle.identity,
    )


def test_policy_bundle_is_deterministic_complete_and_multi_asset_compatible() -> None:
    value = policy()
    assert value.identity == policy().identity
    assert value.identity.startswith("policy-") and len(value.identity) == 71
    assert value.identity != replace(value, fee_policy_version="fees/v2").identity

    future = replace(
        value,
        asset_universe=AssetUniverse(
            (AssetClass.ETF, AssetClass.CASH),
            (MarketVenue.US_NASDAQ, MarketVenue.US_NYSE),
            (Currency.CNY, Currency.USD),
            Currency.CNY,
        ),
    )
    assert MarketVenue.US_NASDAQ in future.asset_universe.market_venues
    assert Currency.USD in future.asset_universe.currencies


def test_manifest_enforces_champion_shadow_fairness_and_independence() -> None:
    value = manifest()
    assert len(value.members) == 4
    assert len({item.account_id for item in value.members}) == 4
    assert {item.policy_bundle_id for item in value.members} == {value.policy_bundle.identity}
    assert {item.initial_capital.amount for item in value.members} == {Decimal("500000")}

    with pytest.raises(ValueError, match="at least three Shadows"):
        replace(value, members=value.members[:3])
    with pytest.raises(ValueError, match="policy bundle"):
        replace(
            value,
            members=(replace(value.members[0], policy_bundle_id="different"), *value.members[1:]),
        )
    with pytest.raises(ValueError, match="unique"):
        replace(
            value,
            members=(
                *value.members[:-1],
                replace(value.members[-1], account_id="account-atlas"),
            ),
        )


def test_sample_states_and_multidimensional_leaderboard_do_not_crown_early_winner() -> None:
    value = manifest()
    session = group_session(value)
    snapshots = tuple(
        performance(member.account_id, return_value, cost)
        for member, return_value, cost in zip(
            value.members,
            ("0.04", "0.08", "0.02", "0.06"),
            ("50", "500", "20", "100"),
            strict=True,
        )
    )
    comparison_policy = ComparisonPolicy(2, 4)
    early = build_comparison_snapshot(
        value,
        session,
        snapshots,
        {member.account_id: 1 for member in value.members},
        comparison_policy,
    )
    assert {item.sample_status for item in early.metrics} == {
        ComparisonSampleStatus.INSUFFICIENT_SAMPLE
    }
    assert early.qualified_winner_account_id is None
    assert early.leaderboard[0].return_rank != early.leaderboard[0].cost_rank

    qualified = build_comparison_snapshot(
        value,
        session,
        snapshots,
        {member.account_id: 4 for member in value.members},
        comparison_policy,
    )
    assert all(
        item.sample_status is ComparisonSampleStatus.QUALIFIED for item in qualified.metrics
    )
    assert qualified.qualified_winner_account_id == qualified.leaderboard[0].account_id


def test_profile_and_session_models_reject_invalid_metadata() -> None:
    with pytest.raises(ValueError, match="must match"):
        definition(RoleIdentity.ATLAS, PortfolioRole.CHAMPION)
    with pytest.raises(ValueError, match="timezone"):
        replace(manifest(), created_at=datetime(2026, 9, 6, 8))
    with pytest.raises(ValueError, match="error_code"):
        MemberSessionResult(
            "account", "source", MemberSessionStatus.FAILED, None, None
        )
    with pytest.raises(ValueError, match="base currency"):
        AssetUniverse(
            (AssetClass.ETF,),
            (MarketVenue.US_NASDAQ,),
            (Currency.USD,),
            Currency.CNY,
        )


def test_fairness_contract_and_activity_aggregation_are_explicit() -> None:
    value = manifest()
    assert value.fairness_contract.policy_bundle_id == value.policy_bundle.identity
    with pytest.raises(ValueError, match="shared dimensions"):
        replace(value.fairness_contract, shared_dimensions=("PIT_POLICY",))
    activities = tuple(
        RoleActivity(
            f"activity-{index}",
            value.group_id,
            None,
            member.account_id,
            member.definition.profile.manager_id,
            NOW,
            RoleActivityStatus.READY if index % 2 else RoleActivityStatus.IDLE,
        )
        for index, member in enumerate(value.members, start=1)
    )
    latest = latest_role_activity(activities)
    assert len(latest) == 4
    assert tuple(item.account_id for item in latest) == tuple(
        sorted(item.account_id for item in activities)
    )
