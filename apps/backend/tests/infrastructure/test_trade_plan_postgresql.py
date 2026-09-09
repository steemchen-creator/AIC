import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from aic_backend.application.trade_plan import CreateDraftPlan, PlanAmendment, TradePlanService
from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market
from aic_backend.domain.portfolio.models import PortfolioId, Quantity
from aic_backend.domain.trade_plan import (
    DirectiveType,
    HardStopPolicy,
    InvestmentHorizon,
    TradePlanError,
    TradePlanErrorCode,
    TradePlanId,
    TradePlanStatus,
    TradingStyle,
)
from aic_backend.infrastructure.trade_plan_persistence import (
    InMemoryTradePlanRepository,
    PostgreSQLTradePlanRepository,
    trade_plan_directives,
    trade_plan_execution_evidence,
    trade_plan_outcomes,
    trade_plan_revisions,
    trade_plans,
)

NOW = datetime(2026, 9, 9, 8, tzinfo=UTC)
NEXT_OPEN = datetime(2026, 9, 10, 1, 30, tzinfo=UTC)
INSTRUMENT = InstrumentIdentity(Market.CN_SSE, "600000", InstrumentType.EQUITY)


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
            trade_plan_outcomes,
            trade_plan_execution_evidence,
            trade_plan_directives,
            trade_plan_revisions,
            trade_plans,
        ):
            await connection.execute(delete(table))
    yield value
    await value.dispose()


class Calendar:
    async def next_open(self, instrument: InstrumentIdentity, decision_at: datetime) -> datetime:
        return NEXT_OPEN


class Execution:
    async def execute(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("persistence fixture must not execute orders")


def command(plan_id: str) -> CreateDraftPlan:
    return CreateDraftPlan(
        TradePlanId(plan_id),
        PortfolioId("champion"),
        INSTRUMENT,
        InvestmentHorizon.MEDIUM_SHORT,
        TradingStyle.TREND,
        "PostgreSQL deterministic fixture",
        Quantity(Decimal("100")),
        NOW,
        hard_stop=HardStopPolicy(Decimal("8")),
    )


async def build(repository: object, plan_id: str) -> object:
    service = TradePlanService(repository, Calendar(), Execution())  # type: ignore[arg-type]
    created = command(plan_id)
    await service.create_draft(created)
    await service.activate(created.plan_id, NOW, actor="aic-codex-cto", source="issue-18")
    await service.revise(
        created.plan_id,
        PlanAmendment(
            1,
            "tighten stop",
            "aic-codex-cto",
            "review",
            NOW,
            hard_stop=HardStopPolicy(Decimal("8.5")),
        ),
    )
    await service.create_directive(
        created.plan_id,
        DirectiveType.HOLD,
        None,
        NOW,
        source_reference="no-action",
    )
    return await repository.get(created.plan_id)  # type: ignore[attr-defined,no-any-return]


@pytest.mark.asyncio
async def test_postgresql_and_in_memory_repository_parity_and_idempotency(
    engine: AsyncEngine,
) -> None:
    memory = InMemoryTradePlanRepository()
    postgres = PostgreSQLTradePlanRepository(engine)
    expected = await build(memory, "parity")
    actual = await build(postgres, "parity")
    assert actual == expected
    assert actual is not None
    await postgres.save(actual)
    assert await postgres.get(TradePlanId("parity")) == actual
    assert await postgres.get_active("champion", INSTRUMENT.canonical_key) == actual
    assert await postgres.list_for_pair("champion", INSTRUMENT.canonical_key) == (actual,)
    directive = actual.directives[0]
    assert await postgres.get_by_directive(directive.directive_id) == (actual, directive)
    async with engine.connect() as connection:
        counts = [
            (await connection.execute(select(func.count()).select_from(table))).scalar_one()
            for table in (trade_plans, trade_plan_revisions, trade_plan_directives)
        ]
    assert counts == [1, 2, 1]


@pytest.mark.asyncio
async def test_database_uniqueness_append_only_and_corrupt_projection_fail_closed(
    engine: AsyncEngine,
) -> None:
    repository = PostgreSQLTradePlanRepository(engine)
    value = await build(repository, "first")
    assert value is not None
    duplicate_service = TradePlanService(repository, Calendar(), Execution())  # type: ignore[arg-type]
    duplicate = command("second")
    await duplicate_service.create_draft(duplicate)
    with pytest.raises(TradePlanError) as error:
        await duplicate_service.activate(
            duplicate.plan_id, NOW, actor="aic-codex-cto", source="issue-18"
        )
    assert error.value.code is TradePlanErrorCode.DUPLICATE_ACTIVE_PLAN
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                update(trade_plans)
                .where(trade_plans.c.plan_id == "second")
                .values(status=TradePlanStatus.ACTIVE.value)
            )

    rewritten = replace(value.revisions[0], reason="REWRITTEN")
    with pytest.raises(Exception, match="append-only"):
        await repository.save(replace(value, revisions=(rewritten,) + value.revisions[1:]))

    async with engine.begin() as connection:
        await connection.execute(
            update(trade_plans)
            .where(trade_plans.c.plan_id == "first")
            .values(recovery_projection={"invalid": True})
        )
    with pytest.raises(Exception, match="stored Trade Plan projection is invalid"):
        await repository.get(TradePlanId("first"))


def test_trade_plan_migration_upgrade_downgrade_and_head() -> None:
    environment = clean_environment()
    for command_parts in (
        ("downgrade", "20260906_0013"),
        ("upgrade", "20260909_0014"),
        ("downgrade", "20260906_0013"),
        ("upgrade", "20260909_0014"),
        ("upgrade", "head"),
        ("downgrade", "base"),
        ("upgrade", "head"),
    ):
        subprocess.run(
            [sys.executable, "-m", "alembic", *command_parts],
            check=True,
            env=environment,
        )
