"""PostgreSQL persistence for deterministic backtest evidence."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Column, DateTime, MetaData, Numeric, String, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from aic_backend.application.ports.backtest import BacktestRecord, BacktestRepository
from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.domain.portfolio.models import (
    BacktestResult,
    BacktestRunId,
    BacktestStatus,
    Money,
)

metadata = MetaData()

backtest_runs = Table(
    "backtest_runs",
    metadata,
    Column("run_id", String(80), primary_key=True),
    Column("portfolio_id", String(80), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("ended_at", DateTime(timezone=True), nullable=False),
    Column("initial_capital", Numeric(38, 10), nullable=False),
    Column("data_policy_version", String(128), nullable=False),
    Column("fee_policy_version", String(128), nullable=False),
    Column("slippage_policy_version", String(128), nullable=False),
    Column("execution_policy_version", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("status", String(32), nullable=False),
    Column("result", JSON, nullable=False),
)

orders = Table(
    "backtest_orders",
    metadata,
    Column("order_id", String(80), primary_key=True),
    Column("run_id", String(80), nullable=False),
    Column("portfolio_id", String(80), nullable=False),
    Column("instrument_key", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
)

fills = Table(
    "backtest_fills",
    metadata,
    Column("fill_id", String(80), primary_key=True),
    Column("run_id", String(80), nullable=False),
    Column("order_id", String(80), nullable=False),
    Column("executed_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
)

cash_ledger = Table(
    "portfolio_cash_ledger",
    metadata,
    Column("entry_id", String(80), primary_key=True),
    Column("run_id", String(80), nullable=False),
    Column("portfolio_id", String(80), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("entry_type", String(32), nullable=False),
    Column("amount", Numeric(38, 10), nullable=False),
    Column("balance_after", Numeric(38, 10), nullable=False),
    Column("source_id", String(80), nullable=False),
)

nav_snapshots = Table(
    "portfolio_nav_snapshots",
    metadata,
    Column("snapshot_id", String(160), primary_key=True),
    Column("run_id", String(80), nullable=False),
    Column("portfolio_id", String(80), nullable=False),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("cash", Numeric(38, 10), nullable=False),
    Column("market_value", Numeric(38, 10), nullable=False),
    Column("nav", Numeric(38, 10), nullable=False),
    Column("payload", JSON, nullable=False),
)

audit_events = Table(
    "backtest_audit_events",
    metadata,
    Column("event_id", String(80), primary_key=True),
    Column("run_id", String(80), nullable=False),
    Column("portfolio_id", String(80), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("source_id", String(160), nullable=False),
    Column("payload", JSON, nullable=False),
)


def _result_json(value: BacktestResult) -> dict[str, object]:
    return {
        "initial_capital": str(value.initial_capital.amount),
        "final_nav": str(value.final_nav.amount),
        "gross_result": str(value.gross_result.amount),
        "fee_total": str(value.fee_total.amount),
        "tax_total": str(value.tax_total.amount),
        "slippage_total": str(value.slippage_total.amount),
        "net_result": str(value.net_result.amount),
        "total_return": str(value.total_return),
        "realized_pnl": str(value.realized_pnl.amount),
        "unrealized_pnl": str(value.unrealized_pnl.amount),
        "trade_count": value.trade_count,
        "benchmark_return": str(value.benchmark_return),
        "excess_return": str(value.excess_return),
        "status": value.status.value,
        "warnings": list(value.warnings),
    }


def _stored_result(run_id: str, value: Mapping[str, Any]) -> BacktestResult:
    def money(key: str) -> Money:
        return Money(Decimal(value[key]))

    return BacktestResult(
        BacktestRunId(run_id),
        money("initial_capital"),
        money("final_nav"),
        money("gross_result"),
        money("fee_total"),
        money("tax_total"),
        money("slippage_total"),
        money("net_result"),
        Decimal(value["total_return"]),
        money("realized_pnl"),
        money("unrealized_pnl"),
        int(value["trade_count"]),
        Decimal(value["benchmark_return"]),
        Decimal(value["excess_return"]),
        BacktestStatus(value["status"]),
        tuple(value["warnings"]),
    )


class PostgreSQLBacktestRepository(BacktestRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, record: BacktestRecord) -> None:
        run = record.run
        run_values = {
            "run_id": run.run_id.value,
            "portfolio_id": run.portfolio_id.value,
            "started_at": run.start,
            "ended_at": run.end,
            "initial_capital": run.initial_capital.amount,
            "data_policy_version": run.data_policy_version,
            "fee_policy_version": run.fee_policy_version,
            "slippage_policy_version": run.slippage_policy_version,
            "execution_policy_version": run.execution_policy_version,
            "created_at": run.created_at,
            "status": record.result.status.value,
            "result": _result_json(record.result),
        }
        try:
            async with self._engine.begin() as connection:
                inserted = (
                    await connection.execute(
                        pg_insert(backtest_runs)
                        .values(**run_values)
                        .on_conflict_do_nothing(index_elements=["run_id"])
                        .returning(backtest_runs.c.run_id)
                    )
                ).scalar_one_or_none()
                if inserted is None:
                    existing = (
                        (
                            await connection.execute(
                                select(backtest_runs).where(
                                    backtest_runs.c.run_id == run.run_id.value
                                )
                            )
                        )
                        .mappings()
                        .one()
                    )
                    if any(existing[key] != value for key, value in run_values.items()):
                        raise PersistenceError(
                            PersistenceErrorCode.IDENTITY_CONFLICT,
                            "run_id identifies different backtest evidence",
                        )
                    return
                await connection.execute(
                    orders.insert(),
                    [
                        {
                            "order_id": item.order_id.value,
                            "run_id": run.run_id.value,
                            "portfolio_id": item.portfolio_id.value,
                            "instrument_key": item.instrument.canonical_key,
                            "created_at": item.created_at,
                            "payload": {
                                "side": item.side.value,
                                "quantity": str(item.quantity.value),
                                "status": item.status.value,
                                "order_type": item.order_type.value,
                                "requested_price": None
                                if item.requested_price is None
                                else str(item.requested_price.value),
                            },
                        }
                        for item in record.orders
                    ],
                )
                await connection.execute(
                    fills.insert(),
                    [
                        {
                            "fill_id": item.fill_id.value,
                            "run_id": run.run_id.value,
                            "order_id": item.order_id.value,
                            "executed_at": item.executed_at,
                            "payload": {
                                "instrument": item.instrument.canonical_key,
                                "side": item.side.value,
                                "quantity": str(item.quantity.value),
                                "price": str(item.fill_price.value),
                                "fee": str(item.fee.amount),
                                "tax": str(item.tax.amount),
                                "slippage": str(item.slippage.amount),
                                "policy_version": item.policy_version,
                            },
                        }
                        for item in record.fills
                    ],
                )
                await connection.execute(
                    cash_ledger.insert(),
                    [
                        {
                            "entry_id": item.entry_id,
                            "run_id": run.run_id.value,
                            "portfolio_id": item.portfolio_id.value,
                            "occurred_at": item.occurred_at,
                            "entry_type": item.entry_type.value,
                            "amount": item.amount.amount,
                            "balance_after": item.balance_after.amount,
                            "source_id": item.source_id,
                        }
                        for item in record.cash_ledger
                    ],
                )
                await connection.execute(
                    nav_snapshots.insert(),
                    [
                        {
                            "snapshot_id": f"{run.run_id.value}:{item.as_of.isoformat()}",
                            "run_id": run.run_id.value,
                            "portfolio_id": item.portfolio_id.value,
                            "as_of": item.as_of,
                            "cash": item.cash.amount,
                            "market_value": item.market_value.amount,
                            "nav": item.nav.amount,
                            "payload": {
                                "realized_pnl": str(item.realized_pnl.amount),
                                "unrealized_pnl": str(item.unrealized_pnl.amount),
                                "positions": [
                                    {
                                        "instrument": p.instrument.canonical_key,
                                        "quantity": str(p.quantity),
                                        "average_cost": str(p.average_cost),
                                        "mark_price": str(p.mark_price),
                                    }
                                    for p in item.positions
                                ],
                            },
                        }
                        for item in record.nav_snapshots
                    ],
                )
                await connection.execute(
                    audit_events.insert(),
                    [
                        {
                            "event_id": item.event_id,
                            "run_id": run.run_id.value,
                            "portfolio_id": item.portfolio_id.value,
                            "occurred_at": item.timestamp,
                            "event_type": item.event_type,
                            "source_id": item.source_id,
                            "payload": dict(item.payload),
                        }
                        for item in record.audit_events
                    ],
                )
        except PersistenceError:
            raise
        except SQLAlchemyError as error:
            raise PersistenceError(
                PersistenceErrorCode.TRANSACTION_ERROR, "backtest persistence transaction failed"
            ) from error

    async def get_result(self, run_id: str) -> BacktestResult | None:
        try:
            async with self._engine.connect() as connection:
                row = (
                    await connection.execute(
                        select(backtest_runs.c.result).where(backtest_runs.c.run_id == run_id)
                    )
                ).scalar_one_or_none()
            return None if row is None else _stored_result(run_id, row)
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as error:
            raise PersistenceError(
                PersistenceErrorCode.SERIALIZATION_ERROR, "stored backtest result is invalid"
            ) from error


class InMemoryBacktestRepository(BacktestRepository):
    def __init__(self) -> None:
        self._records: dict[str, BacktestRecord] = {}

    async def save(self, record: BacktestRecord) -> None:
        key = record.run.run_id.value
        existing = self._records.get(key)
        if existing is not None and existing != record:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT,
                "run_id identifies different backtest evidence",
            )
        self._records[key] = record

    async def get_result(self, run_id: str) -> BacktestResult | None:
        record = self._records.get(run_id)
        return None if record is None else record.result
