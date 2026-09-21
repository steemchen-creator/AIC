"""PostgreSQL claims survive crashes; completed receipts are insert-or-verify."""

from collections.abc import Mapping
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from aic_backend.application.ports.execution_journal import ExecutionClaim, ExecutionReceipt
from aic_backend.application.ports.persistence import PersistenceError, PersistenceErrorCode
from aic_backend.domain.portfolio.models import OrderId

execution_claims = Table(
    "execution_order_claims",
    MetaData(),
    Column("order_id", String(80), primary_key=True),
    Column("portfolio_id", String(80), nullable=False),
    Column("requested_at", DateTime(timezone=True), nullable=False),
    Column("claim", JSON, nullable=False),
    Column("receipt", JSON),
)
_CLAIM = TypeAdapter(ExecutionClaim)
_RECEIPT = TypeAdapter(ExecutionReceipt)


def _fallback(value: Any) -> Any:
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError("unsupported execution journal value")


def _json(value: ExecutionClaim | ExecutionReceipt) -> Any:
    if isinstance(value, ExecutionClaim):
        return _CLAIM.dump_python(value, mode="json", warnings="none", fallback=_fallback)
    return _RECEIPT.dump_python(value, mode="json", warnings="none", fallback=_fallback)


class PostgreSQLExecutionJournal:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, order_id: OrderId) -> ExecutionClaim | ExecutionReceipt | None:
        try:
            async with self._engine.connect() as connection:
                row = (
                    (
                        await connection.execute(
                            select(execution_claims).where(
                                execution_claims.c.order_id == order_id.value
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            if row is None:
                return None
            claim = _CLAIM.validate_python(row["claim"])
            if claim.order_id != order_id or claim.before.portfolio_id.value != row["portfolio_id"]:
                raise ValueError("journal identity mismatch")
            if row["receipt"] is None:
                return claim
            receipt = _RECEIPT.validate_python(row["receipt"])
            if receipt.claim != claim:
                raise ValueError("receipt claim mismatch")
            return receipt
        except (SQLAlchemyError, ValueError, TypeError, KeyError) as error:
            raise PersistenceError(
                PersistenceErrorCode.SERIALIZATION_ERROR, "execution journal read failed"
            ) from error

    async def claim(self, value: ExecutionClaim) -> bool:
        try:
            async with self._engine.begin() as connection:
                key = (
                    await connection.execute(
                        insert(execution_claims)
                        .values(
                            order_id=value.order_id.value,
                            portfolio_id=value.before.portfolio_id.value,
                            requested_at=value.requested_at,
                            claim=_json(value),
                        )
                        .on_conflict_do_nothing(index_elements=["order_id"])
                        .returning(execution_claims.c.order_id)
                    )
                ).scalar_one_or_none()
            return key is not None
        except SQLAlchemyError as error:
            raise PersistenceError(
                PersistenceErrorCode.TRANSACTION_ERROR, "execution claim failed"
            ) from error

    async def complete(self, value: ExecutionReceipt) -> None:
        try:
            async with self._engine.begin() as connection:
                row = (
                    (
                        await connection.execute(
                            select(execution_claims)
                            .where(execution_claims.c.order_id == value.claim.order_id.value)
                            .with_for_update()
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None or _CLAIM.validate_python(row["claim"]) != value.claim:
                    raise PersistenceError(
                        PersistenceErrorCode.IDENTITY_CONFLICT, "execution claim ownership mismatch"
                    )
                if row["receipt"] is not None:
                    if _RECEIPT.validate_python(row["receipt"]) != value:
                        raise PersistenceError(
                            PersistenceErrorCode.IDENTITY_CONFLICT, "execution receipt is immutable"
                        )
                    return
                await connection.execute(
                    update(execution_claims)
                    .where(execution_claims.c.order_id == value.claim.order_id.value)
                    .values(receipt=_json(value))
                )
        except (SQLAlchemyError, ValueError, TypeError) as error:
            raise PersistenceError(
                PersistenceErrorCode.TRANSACTION_ERROR, "execution receipt transaction failed"
            ) from error


class InMemoryExecutionJournal:
    """Deterministic test/research adapter; production requires durable storage."""

    def __init__(self) -> None:
        self._entries: dict[str, ExecutionClaim | ExecutionReceipt] = {}

    async def get(self, order_id: OrderId) -> ExecutionClaim | ExecutionReceipt | None:
        return self._entries.get(order_id.value)

    async def claim(self, value: ExecutionClaim) -> bool:
        if value.order_id.value in self._entries:
            return False
        self._entries[value.order_id.value] = value
        return True

    async def complete(self, value: ExecutionReceipt) -> None:
        prior = self._entries.get(value.claim.order_id.value)
        if prior != value.claim and prior != value:
            raise PersistenceError(
                PersistenceErrorCode.IDENTITY_CONFLICT, "execution claim conflict"
            )
        self._entries[value.claim.order_id.value] = value
