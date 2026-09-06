import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.application.ports.experiments import ShadowExperimentRecord
from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.domain.experiments import (
    AssetClass,
    AssetUniverse,
    ComparisonMetrics,
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
    LeaderboardEntry,
    ManagerProfile,
    MarketVenue,
    MemberSessionResult,
    MemberSessionStatus,
    PerformanceComparisonSnapshot,
    PortfolioRole,
    RoleActivity,
    RoleActivityStatus,
    RoleIdentity,
    TradingStyle,
)
from aic_backend.domain.portfolio.models import Money, PortfolioId
from aic_backend.infrastructure.experiment_persistence import (
    InMemoryShadowExperimentRepository,
    PostgreSQLShadowExperimentRepository,
    shadow_comparison_snapshots,
    shadow_experiment_groups,
    shadow_experiment_members,
    shadow_group_sessions,
    shadow_role_activities,
)

NOW = datetime(2026, 9, 7, 8, tzinfo=UTC)
DAY = date(2026, 9, 7)


def clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COV_CORE_") or name == "COVERAGE_PROCESS_START":
            del environment[name]
    return environment


@pytest.fixture
async def engine() -> AsyncEngine:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=clean_environment(),
    )
    value = create_async_engine(os.environ["AIC_DATABASE_URL"], pool_pre_ping=True)
    async with value.begin() as connection:
        for table in (
            shadow_role_activities,
            shadow_comparison_snapshots,
            shadow_group_sessions,
            shadow_experiment_members,
            shadow_experiment_groups,
        ):
            await connection.execute(delete(table))
    yield value
    await value.dispose()


def policy() -> ExperimentPolicyBundle:
    return ExperimentPolicyBundle(
        "pit-operational-replay/v1",
        "a-share-calendar/v1",
        "next-session-open/v1",
        "a-share-risk/v1",
        "a-share-fees/v1",
        "fixed-bps/v1",
        "CN.SSE.000001",
        Money(Decimal("500000")),
        DAY,
        "shadow-experiment/v1",
        "shadow-comparison/v1",
        AssetUniverse(
            (AssetClass.CASH, AssetClass.EQUITY),
            (MarketVenue.CN_SSE, MarketVenue.CN_SZSE),
            (Currency.CNY,),
            Currency.CNY,
        ),
    )


def member(
    bundle: ExperimentPolicyBundle,
    role: RoleIdentity,
    portfolio_role: PortfolioRole,
) -> ExperimentMember:
    definition = ExperimentMemberDefinition(
        portfolio_role,
        ManagerProfile(
            f"manager-{role.value.lower()}",
            role.value.title(),
            f"{role.value.title()} Manager",
            f"Mandate {role.value}",
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
            f"fixture/{role.value.lower()}.json",
        ),
    )
    return ExperimentMember(
        f"account-{role.value.lower()}",
        PortfolioId(f"portfolio-{role.value.lower()}"),
        definition,
        bundle.identity,
        bundle.initial_capital,
    )


def record() -> ShadowExperimentRecord:
    bundle = policy()
    members = tuple(
        member(bundle, role, portfolio_role)
        for role, portfolio_role in (
            (RoleIdentity.CHAMPION, PortfolioRole.CHAMPION),
            (RoleIdentity.ATLAS, PortfolioRole.SHADOW),
            (RoleIdentity.SAGE, PortfolioRole.SHADOW),
            (RoleIdentity.AEGIS, PortfolioRole.SHADOW),
        )
    )
    contract = FairnessContract(
        "fairness-postgresql",
        bundle.identity,
        bundle.initial_capital,
        tuple(item.account_id for item in members),
        tuple(sorted(FairnessContract.REQUIRED_DIMENSIONS)),
        NOW,
    )
    manifest = ExperimentManifest(
        "postgresql-lab", "PostgreSQL Lab", bundle, members, contract, NOW
    )
    member_results = tuple(
        MemberSessionResult(
            item.account_id,
            item.definition.decision_source.source_id,
            MemberSessionStatus.SKIPPED,
            None,
            None,
        )
        for item in members
    )
    session = GroupTradingSession(
        "group-session-postgresql",
        manifest.group_id,
        DAY,
        NOW,
        NOW,
        NOW,
        GroupSessionStatus.SKIPPED,
        member_results,
        bundle.identity,
    )
    metrics = ComparisonMetrics(
        members[0].account_id,
        Money(Decimal("500000")),
        Decimal("0"),
        Decimal("0"),
        None,
        None,
        None,
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Money(Decimal("0")),
        Money(Decimal("0")),
        Money(Decimal("500000")),
        0,
        ComparisonSampleStatus.INSUFFICIENT_SAMPLE,
    )
    leaderboard = LeaderboardEntry(
        members[0].account_id,
        1,
        1,
        1,
        1,
        1,
        ComparisonSampleStatus.INSUFFICIENT_SAMPLE,
    )
    comparison = PerformanceComparisonSnapshot(
        "comparison-postgresql",
        manifest.group_id,
        session.group_session_id,
        DAY,
        NOW,
        bundle.identity,
        (metrics,),
        (leaderboard,),
        None,
    )
    activity = RoleActivity(
        "activity-postgresql",
        manifest.group_id,
        session.group_session_id,
        members[0].account_id,
        members[0].definition.profile.manager_id,
        NOW,
        RoleActivityStatus.READY,
    )
    return ShadowExperimentRecord(manifest, (session,), (comparison,), (activity,))


@pytest.mark.asyncio
async def test_in_memory_experiment_manifest_and_evidence_are_immutable() -> None:
    repository = InMemoryShadowExperimentRepository()
    value = record()
    await repository.save(value)
    assert await repository.get(value.manifest.group_id) == value
    with pytest.raises(PersistenceError) as error:
        await repository.save(replace(value, sessions=()))
    assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT
    with pytest.raises(PersistenceError) as error:
        await repository.save(
            replace(value, manifest=replace(value.manifest, display_name="Changed"))
        )
    assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT


@pytest.mark.asyncio
async def test_postgresql_experiment_round_trip_normalized_evidence_and_idempotency(
    engine: AsyncEngine,
) -> None:
    repository = PostgreSQLShadowExperimentRepository(engine)
    value = record()
    await repository.save(value)
    await repository.save(value)
    assert await repository.get(value.manifest.group_id) == value
    assert await repository.get("missing") is None
    async with engine.connect() as connection:
        counts = [
            (await connection.execute(select(func.count()).select_from(table))).scalar_one()
            for table in (
                shadow_experiment_groups,
                shadow_experiment_members,
                shadow_group_sessions,
                shadow_comparison_snapshots,
                shadow_role_activities,
            )
        ]
    assert counts == [1, 4, 1, 1, 1]


@pytest.mark.asyncio
async def test_postgresql_rejects_normalized_conflict_and_corrupt_projection(
    engine: AsyncEngine,
) -> None:
    repository = PostgreSQLShadowExperimentRepository(engine)
    value = record()
    await repository.save(value)
    async with engine.begin() as connection:
        await connection.execute(
            update(shadow_group_sessions)
            .where(
                shadow_group_sessions.c.group_session_id
                == value.sessions[0].group_session_id
            )
            .values(status=GroupSessionStatus.FINALIZED.value)
        )
    with pytest.raises(PersistenceError) as error:
        await repository.save(value)
    assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT

    async with engine.begin() as connection:
        await connection.execute(
            update(shadow_experiment_groups)
            .where(shadow_experiment_groups.c.group_id == value.manifest.group_id)
            .values(recovery_projection={"invalid": True})
        )
    with pytest.raises(PersistenceError) as error:
        await repository.get(value.manifest.group_id)
    assert error.value.code is PersistenceErrorCode.SERIALIZATION_ERROR


def test_shadow_experiment_migration_upgrade_downgrade_and_head() -> None:
    environment = clean_environment()
    for command in (
        ("downgrade", "20260904_0010"),
        ("upgrade", "20260906_0011"),
        ("downgrade", "20260904_0010"),
        ("upgrade", "head"),
    ):
        subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            check=True,
            env=environment,
        )
