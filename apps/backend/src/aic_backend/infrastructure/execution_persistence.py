"""Insert-or-verify PostgreSQL persistence for execution and risk evidence."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Column, Date, DateTime, MetaData, Numeric, String, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from aic_backend.application.ports.execution import ExecutionEvidenceRepository
from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.domain.execution import (
    ExecutionOutcome,
    ExecutionPolicyVersions,
    RiskDecision,
    RiskDecisionType,
    RiskInputSummary,
    RiskReasonCode,
)
from aic_backend.domain.portfolio.models import Money, OrderId, PortfolioId

metadata = MetaData()

risk_decisions = Table(
    "risk_decisions",
    metadata,
    Column("risk_decision_id", String(80), primary_key=True),
    Column("portfolio_id", String(80), nullable=False),
    Column("order_id", String(80), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("decision", String(16), nullable=False),
    Column("reason_codes", JSON, nullable=False),
    Column("policy_version", String(128), nullable=False),
    Column("execution_policy_versions", JSON, nullable=False),
    Column("input_summary", JSON, nullable=False),
)

risk_snapshots = Table(
    "execution_risk_snapshots",
    metadata,
    Column("snapshot_id", String(80), primary_key=True),
    Column("portfolio_id", String(80), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("nav", Numeric(38, 10), nullable=False),
    Column("cash", Numeric(38, 10), nullable=False),
    Column("gross_exposure", Numeric(38, 10), nullable=False),
    Column("payload", JSON, nullable=False),
)

settlement_rollovers = Table(
    "settlement_rollovers",
    metadata,
    Column("event_id", String(80), primary_key=True),
    Column("portfolio_id", String(80), nullable=False),
    Column("trading_date", Date, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("released_quantity", Numeric(38, 10), nullable=False),
    Column("policy_version", String(128), nullable=False),
)

settlement_positions = Table(
    "settlement_position_evidence",
    metadata,
    Column("evidence_id", String(160), primary_key=True),
    Column("portfolio_id", String(80), nullable=False),
    Column("order_id", String(80), nullable=False),
    Column("instrument_key", String(128), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("total_quantity", Numeric(38, 10), nullable=False),
    Column("sellable_quantity", Numeric(38, 10), nullable=False),
    Column("today_bought_quantity", Numeric(38, 10), nullable=False),
    Column("policy_version", String(128), nullable=False),
)

execution_audit_events = Table(
    "execution_audit_events",
    metadata,
    Column("event_id", String(80), primary_key=True),
    Column("portfolio_id", String(80), nullable=False),
    Column("order_id", String(80), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("source_id", String(160), nullable=False),
    Column("payload", JSON, nullable=False),
)


def _summary_json(value: RiskInputSummary) -> dict[str, object]:
    return {
        "nav": str(value.nav.amount),
        "cash": str(value.cash.amount),
        "current_gross_exposure": str(value.current_gross_exposure.amount),
        "post_trade_gross_exposure": str(value.post_trade_gross_exposure.amount),
        "post_trade_position_exposure": str(value.post_trade_position_exposure.amount),
        "post_trade_cash": str(value.post_trade_cash.amount),
        "orders_today": value.orders_today,
        "filled_orders_today": value.filled_orders_today,
        "daily_turnover": str(value.daily_turnover.amount),
    }


def _decision_values(value: RiskDecision, versions: ExecutionPolicyVersions) -> dict[str, object]:
    return {
        "risk_decision_id": value.risk_decision_id,
        "portfolio_id": value.portfolio_id.value,
        "order_id": value.order_id.value,
        "as_of": value.as_of,
        "decision": value.decision.value,
        "reason_codes": [item.value for item in value.reason_codes],
        "policy_version": value.policy_version,
        "execution_policy_versions": {
            "execution": versions.execution,
            "lot": versions.lot,
            "price_limit": versions.price_limit,
            "settlement": versions.settlement,
            "risk": versions.risk,
        },
        "input_summary": _summary_json(value.input_summary),
    }


def _stored_decision(row: Mapping[str, Any] | Any) -> RiskDecision:
    summary = row["input_summary"]
    return RiskDecision(
        row["risk_decision_id"],
        PortfolioId(row["portfolio_id"]),
        OrderId(row["order_id"]),
        row["as_of"],
        RiskDecisionType(row["decision"]),
        tuple(RiskReasonCode(item) for item in row["reason_codes"]),
        row["policy_version"],
        RiskInputSummary(
            Money(Decimal(summary["nav"])),
            Money(Decimal(summary["cash"])),
            Money(Decimal(summary["current_gross_exposure"])),
            Money(Decimal(summary["post_trade_gross_exposure"])),
            Money(Decimal(summary["post_trade_position_exposure"])),
            Money(Decimal(summary["post_trade_cash"])),
            int(summary["orders_today"]),
            int(summary["filled_orders_today"]),
            Money(Decimal(summary["daily_turnover"])),
        ),
    )


class PostgreSQLExecutionEvidenceRepository(ExecutionEvidenceRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, outcome: ExecutionOutcome) -> None:
        decision = outcome.risk_decision
        records: list[tuple[Table, str, dict[str, object]]] = [
            (
                risk_decisions,
                "risk_decision_id",
                _decision_values(decision, outcome.policy_versions),
            )
        ]
        if outcome.risk_snapshot is not None:
            snapshot = outcome.risk_snapshot
            records.append(
                (
                    risk_snapshots,
                    "snapshot_id",
                    {
                        "snapshot_id": snapshot.snapshot_id,
                        "portfolio_id": snapshot.portfolio_id.value,
                        "as_of": snapshot.as_of,
                        "nav": snapshot.nav.amount,
                        "cash": snapshot.cash.amount,
                        "gross_exposure": snapshot.gross_exposure.amount,
                        "payload": {
                            "cash_pct": str(snapshot.cash_pct),
                            "largest_position_pct": str(snapshot.largest_position_pct),
                            "position_count": snapshot.position_count,
                            "daily_turnover": str(snapshot.daily_turnover.amount),
                            "orders_today": snapshot.orders_today,
                            "filled_orders_today": snapshot.filled_orders_today,
                            "policy_version": snapshot.policy_version,
                        },
                    },
                )
            )
        if outcome.settlement_event is not None:
            event = outcome.settlement_event
            records.append(
                (
                    settlement_rollovers,
                    "event_id",
                    {
                        "event_id": event.event_id,
                        "portfolio_id": event.portfolio_id.value,
                        "trading_date": event.trading_date,
                        "occurred_at": event.occurred_at,
                        "released_quantity": event.released_quantity,
                        "policy_version": event.policy_version,
                    },
                )
            )
        if outcome.settlement_position is not None:
            position = outcome.settlement_position
            records.append(
                (
                    settlement_positions,
                    "evidence_id",
                    {
                        "evidence_id": f"{outcome.order.order_id.value}:settlement",
                        "portfolio_id": outcome.order.portfolio_id.value,
                        "order_id": outcome.order.order_id.value,
                        "instrument_key": position.instrument.canonical_key,
                        "as_of": outcome.risk_decision.as_of,
                        "total_quantity": position.total_quantity,
                        "sellable_quantity": position.sellable_quantity,
                        "today_bought_quantity": position.today_bought_quantity,
                        "policy_version": outcome.policy_versions.settlement,
                    },
                )
            )
        records.extend(
            (
                execution_audit_events,
                "event_id",
                {
                    "event_id": event.event_id,
                    "portfolio_id": event.portfolio_id.value,
                    "order_id": outcome.order.order_id.value,
                    "occurred_at": event.timestamp,
                    "event_type": event.event_type,
                    "source_id": event.source_id,
                    "payload": dict(event.payload),
                },
            )
            for event in outcome.audit_events
        )
        try:
            async with self._engine.begin() as connection:
                for table, identity_column, values in records:
                    await self._insert_or_verify(connection, table, identity_column, values)
        except PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise PersistenceError(
                PersistenceErrorCode.TRANSACTION_ERROR,
                "execution evidence transaction failed",
            ) from error

    async def get_risk_decision(self, risk_decision_id: str) -> RiskDecision | None:
        try:
            async with self._engine.connect() as connection:
                row = (
                    (
                        await connection.execute(
                            select(risk_decisions).where(
                                risk_decisions.c.risk_decision_id == risk_decision_id
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            return None if row is None else _stored_decision(row)
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as error:
            raise PersistenceError(
                PersistenceErrorCode.SERIALIZATION_ERROR,
                "stored risk decision is invalid",
            ) from error

    @staticmethod
    async def _insert_or_verify(
        connection: AsyncConnection,
        table: Table,
        identity_column: str,
        values: dict[str, object],
    ) -> None:
        inserted = (
            await connection.execute(
                pg_insert(table)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[identity_column])
                .returning(table.c[identity_column])
            )
        ).scalar_one_or_none()
        if inserted is not None:
            return
        existing = (
            (
                await connection.execute(
                    select(table).where(table.c[identity_column] == values[identity_column])
                )
            )
            .mappings()
            .one()
        )
        if any(existing[key] != value for key, value in values.items()):
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT,
                f"{identity_column} identifies different execution evidence",
            )


class InMemoryExecutionEvidenceRepository(ExecutionEvidenceRepository):
    def __init__(self) -> None:
        self._outcomes: dict[str, ExecutionOutcome] = {}

    async def save(self, outcome: ExecutionOutcome) -> None:
        key = outcome.risk_decision.risk_decision_id
        existing = self._outcomes.get(key)
        if existing is not None and existing != outcome:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT,
                "risk_decision_id identifies different execution evidence",
            )
        self._outcomes[key] = outcome

    async def get_risk_decision(self, risk_decision_id: str) -> RiskDecision | None:
        outcome = self._outcomes.get(risk_decision_id)
        return None if outcome is None else outcome.risk_decision
