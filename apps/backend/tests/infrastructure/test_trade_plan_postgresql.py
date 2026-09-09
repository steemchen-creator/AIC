import asyncio
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.application.trade_plan import CreateDraftPlan, PlanAmendment, TradePlanService
from aic_backend.application.trade_plan_record import TradePlanRecord
from aic_backend.domain.market_data import InstrumentIdentity, InstrumentType, Market
from aic_backend.domain.portfolio.models import PortfolioId, Quantity
from aic_backend.domain.trade_plan import (
    DirectiveType,
    HardStopPolicy,
    InvestmentHorizon,
    PlanExecutionEvidence,
    TradePlanError,
    TradePlanErrorCode,
    TradePlanId,
    TradePlanStatus,
    TradingStyle,
)
from aic_backend.infrastructure.execution_journal import execution_claims
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
            execution_claims,
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


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["revision", "directive", "execution"])
async def test_concurrent_append_cannot_overwrite_projection_or_evidence(
    engine: AsyncEngine, kind: str
) -> None:
    repository = PostgreSQLTradePlanRepository(engine)
    initial = await build(repository, "concurrent")
    if kind == "execution":
        initial = replace(
            initial,
            directives=initial.directives
            + tuple(
                replace(
                    initial.directives[0],
                    directive_id=f"execute-{name}",
                    directive_type=DirectiveType.ENTRY,
                    quantity=Quantity(Decimal("100")),
                    not_before=NEXT_OPEN,
                )
                for name in ("first", "second")
            ),
        )
        await repository.save(initial)

    def append(record: TradePlanRecord, writer: str) -> TradePlanRecord:
        if kind == "revision":
            version = record.plan.version + 1
            at = NOW + timedelta(minutes=version)
            revision = replace(
                record.revisions[-1],
                version=version,
                reason=writer,
                effective_at=at,
                recorded_at=at,
            )
            return replace(
                record,
                plan=replace(record.plan, version=version, updated_at=at),
                revisions=record.revisions + (revision,),
            )
        if kind == "directive":
            directive = replace(record.directives[0], directive_id=f"directive-{writer}")
            return replace(record, directives=record.directives + (directive,))
        execution = PlanExecutionEvidence(
            f"evidence-{writer}",
            record.plan.plan_id,
            record.plan.version,
            f"execute-{writer}",
            DirectiveType.ENTRY,
            f"order-{writer}",
            f"fill-{writer}",
            NEXT_OPEN,
        )
        return replace(record, executions=record.executions + (execution,))

    written = asyncio.Event()
    release = asyncio.Event()

    class PausingRepository(PostgreSQLTradePlanRepository):
        async def _save_projection(
            self, connection: AsyncConnection, record: TradePlanRecord, create: bool
        ) -> None:
            await super()._save_projection(connection, record, create)
            written.set()
            await release.wait()

    waiter_engine = create_async_engine(
        os.environ["AIC_DATABASE_URL"],
        connect_args={"server_settings": {"application_name": "spec010-concurrent-waiter"}},
    )
    first_task = asyncio.create_task(PausingRepository(engine).save(append(initial, "first")))
    second_task = None
    try:
        await asyncio.wait_for(written.wait(), timeout=10)
        second_task = asyncio.create_task(
            PostgreSQLTradePlanRepository(waiter_engine).save(append(initial, "second"))
        )
        # Observe an actual database lock wait, rather than relying on scheduling delays.
        async with asyncio.timeout(10):
            async with engine.connect() as observer:
                while not (
                    await observer.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE application_name = :name AND wait_event_type = 'Lock'"
                        ),
                        {"name": "spec010-concurrent-waiter"},
                    )
                ).scalar_one():
                    await observer.rollback()
                    await asyncio.sleep(0.01)
        release.set()
        results = await asyncio.gather(first_task, second_task, return_exceptions=True)
        assert results[0] is None
        assert isinstance(results[1], PersistenceError)
        assert results[1].code is PersistenceErrorCode.IDENTITY_CONFLICT
        assert await repository.get(initial.plan.plan_id) == append(initial, "first")
        # The rejected caller can reload and explicitly append; neither writer's evidence vanishes.
        current = await repository.get(initial.plan.plan_id)
        final = append(current, "second")
        await repository.save(final)
        await repository.save(final)
        assert await repository.get(initial.plan.plan_id) == final
        async with engine.connect() as connection:
            for table, values in (
                (trade_plan_revisions, final.revisions),
                (trade_plan_directives, final.directives),
                (trade_plan_execution_evidence, final.executions),
            ):
                count = (
                    await connection.execute(
                        select(func.count())
                        .select_from(table)
                        .where(table.c.plan_id == final.plan.plan_id.value)
                    )
                ).scalar_one()
                assert count == len(values)
    finally:
        release.set()
        await asyncio.gather(
            *(task for task in (first_task, second_task) if task is not None),
            return_exceptions=True,
        )
        await waiter_engine.dispose()


@pytest.mark.asyncio
async def test_postgresql_rejects_draft_instrument_mutation(engine: AsyncEngine) -> None:
    repository = PostgreSQLTradePlanRepository(engine)
    service = TradePlanService(repository, Calendar(), Execution())  # type: ignore[arg-type]
    created = command("draft-identity")
    await service.create_draft(created)
    before = await repository.get(created.plan_id)
    changed = replace(
        before,
        plan=replace(
            before.plan, instrument=InstrumentIdentity(Market.CN_SSE, "510300", InstrumentType.ETF)
        ),
    )
    with pytest.raises(PersistenceError) as error:
        await repository.save(changed)
    assert error.value.code is PersistenceErrorCode.IDENTITY_CONFLICT
    assert await repository.get(created.plan_id) == before


@pytest.mark.asyncio
async def test_legacy_directive_payload_remains_appendable(engine: AsyncEngine) -> None:
    repository = PostgreSQLTradePlanRepository(engine)
    record = await build(repository, "legacy")
    async with engine.begin() as connection:
        payload = (await connection.execute(select(trade_plan_directives.c.payload))).scalar_one()
        payload.pop("trigger_key", None)
        await connection.execute(update(trade_plan_directives).values(payload=payload))
    await repository.save(record)
    assert await repository.get(record.plan.plan_id) == record
