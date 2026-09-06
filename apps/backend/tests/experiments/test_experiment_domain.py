from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from aic_backend.application.ports.experiments import ShadowExperimentRecord
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
    RoleAvatarReferenceUpdated,
    RoleIdentity,
    TradingStyle,
    build_comparison_snapshot,
    build_role_activity_board,
    current_manager_profile,
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
    assert value.identity != replace(
        value, comparison_policy_version="shadow-comparison/v2"
    ).identity

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

    tied = build_comparison_snapshot(
        value,
        session,
        tuple(performance(member.account_id, "0.01", "10") for member in value.members),
        {member.account_id: 4 for member in value.members},
        comparison_policy,
    )
    assert tuple(item.account_id for item in tied.leaderboard) == tuple(
        sorted(member.account_id for member in value.members)
    )


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


def test_domain_rejects_invalid_manifest_policy_and_session_boundaries() -> None:
    value = manifest()
    with pytest.raises(ValueError, match="must not be empty"):
        replace(value, display_name=" ")
    with pytest.raises(ValueError, match="dimensions"):
        replace(value.policy_bundle.asset_universe, asset_classes=())
    with pytest.raises(ValueError, match="duplicates"):
        replace(
            value.policy_bundle.asset_universe,
            currencies=(Currency.CNY, Currency.CNY),
        )
    with pytest.raises(ValueError, match="positive"):
        replace(value.policy_bundle, initial_capital=Money(Decimal("0")))
    with pytest.raises(ValueError, match="currency"):
        replace(
            value.policy_bundle,
            asset_universe=AssetUniverse(
                (AssetClass.EQUITY,),
                (MarketVenue.US_NASDAQ,),
                (Currency.USD,),
                Currency.USD,
            ),
        )
    with pytest.raises(ValueError, match="horizon"):
        replace(value.members[0].definition.profile, horizons=())

    contract = value.fairness_contract
    with pytest.raises(ValueError, match="unique"):
        replace(contract, member_account_ids=(value.members[0].account_id,) * 2)
    with pytest.raises(ValueError, match="requires members"):
        replace(contract, member_account_ids=())
    with pytest.raises(ValueError, match="equal initial capital"):
        replace(
            value,
            members=(
                replace(value.members[0], initial_capital=Money(Decimal("1"))),
                *value.members[1:],
            ),
        )
    with pytest.raises(ValueError, match="manifest policy bundle"):
        replace(value, fairness_contract=replace(contract, policy_bundle_id="different"))
    with pytest.raises(ValueError, match="equal initial capital"):
        replace(
            value,
            fairness_contract=replace(contract, initial_capital=Money(Decimal("1"))),
        )
    with pytest.raises(ValueError, match="every experiment member"):
        replace(
            value,
            fairness_contract=replace(
                contract,
                member_account_ids=(*contract.member_account_ids[:-1], "other-account"),
            ),
        )

    valid_result = group_session(value).member_results[0]
    with pytest.raises(ValueError, match="non-failed"):
        replace(valid_result, error_code="UNEXPECTED")
    with pytest.raises(ValueError, match="before"):
        replace(
            group_session(value),
            started_at=NOW,
            finalized_at=NOW - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="duplicate account"):
        replace(
            group_session(value),
            member_results=(valid_result, valid_result),
        )

    with pytest.raises(ValueError, match="positive"):
        ComparisonPolicy(0, 1)
    with pytest.raises(ValueError, match="precede"):
        ComparisonPolicy(2, 1)
    comparison_policy = ComparisonPolicy(2, 4)
    assert comparison_policy.sample_status(2) is ComparisonSampleStatus.PROVISIONAL


def test_avatar_event_and_activity_board_preserve_identity_and_real_references() -> None:
    value = manifest()
    member = value.members[1]
    event = RoleAvatarReferenceUpdated(
        "avatar-event-1",
        value.group_id,
        member.account_id,
        member.definition.profile.manager_id,
        member.definition.profile.avatar_reference,
        "avatars/atlas-v2.svg",
        NOW,
    )
    current = current_manager_profile(member, (event,))
    assert current.avatar_reference == "avatars/atlas-v2.svg"
    assert current.manager_id == member.definition.profile.manager_id

    activity = RoleActivity(
        "activity-processing",
        value.group_id,
        "group-session-current",
        member.account_id,
        member.definition.profile.manager_id,
        NOW,
        RoleActivityStatus.PAUSED,
        "DEPENDENCY_PAUSED",
        "group-session-current",
        "snapshot-prior",
    )
    board = build_role_activity_board(value, (activity,), (event,))
    atlas = next(item for item in board if item.paper_account_id == member.account_id)
    assert atlas.current_status is RoleActivityStatus.PAUSED
    assert atlas.current_task_reference == "group-session-current"
    assert atlas.latest_session_reference == "group-session-current"
    assert atlas.latest_output_reference == "snapshot-prior"
    assert atlas.avatar_reference == "avatars/atlas-v2.svg"
    assert {
        item.current_status
        for item in board
        if item.paper_account_id != member.account_id
    } == {RoleActivityStatus.IDLE}

    with pytest.raises(ValueError, match="safe reference"):
        replace(event, new_avatar_reference="avatars/atlas\nunsafe.svg")
    with pytest.raises(ValueError, match="must change"):
        replace(event, new_avatar_reference=event.previous_avatar_reference)


def test_experiment_record_rejects_unbound_activity_and_avatar_audit_evidence() -> None:
    value = manifest()
    session = group_session(value)
    member = value.members[1]
    activity = RoleActivity(
        "activity-bound",
        value.group_id,
        session.group_session_id,
        member.account_id,
        member.definition.profile.manager_id,
        NOW,
        RoleActivityStatus.READY,
    )
    event = RoleAvatarReferenceUpdated(
        "avatar-event-bound",
        value.group_id,
        member.account_id,
        member.definition.profile.manager_id,
        member.definition.profile.avatar_reference,
        "avatars/atlas-v2.svg",
        NOW,
    )
    assert ShadowExperimentRecord(value, (session,), (), (activity,), (event,))

    for invalid, message in (
        (replace(activity, account_id="unknown"), "activity account"),
        (replace(activity, group_id="other"), "activity group"),
        (replace(activity, manager_id="other"), "activity manager"),
        (replace(activity, group_session_id="other"), "activity session"),
    ):
        with pytest.raises(ValueError, match=message):
            ShadowExperimentRecord(value, (session,), (), (invalid,))

    with pytest.raises(ValueError, match="identities must be unique"):
        ShadowExperimentRecord(value, (session,), (), (), (event, event))
    for invalid, message in (
        (replace(event, account_id="unknown"), "event account"),
        (replace(event, group_id="other"), "event group"),
        (replace(event, manager_id="other"), "event manager"),
        (replace(event, previous_avatar_reference="avatars/other.svg"), "audit chain"),
    ):
        with pytest.raises(ValueError, match=message):
            ShadowExperimentRecord(value, (session,), (), (), (invalid,))
