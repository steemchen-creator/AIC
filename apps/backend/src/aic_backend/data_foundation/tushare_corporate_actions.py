"""Tushare adj_factor and dividend normalization."""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from aic_backend.data_foundation.identity import raw_payload_hash
from aic_backend.domain.market_data import (
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
)
from aic_backend.domain.market_data.corporate_actions import (
    AdjustmentFactor,
    CorporateAction,
    CorporateActionType,
)

_SUFFIXES = {"SH": Market.CN_SSE, "SZ": Market.CN_SZSE}


def _identity(value: object) -> InstrumentIdentity:
    parts = str(value).strip().upper().split(".")
    if len(parts) != 2 or parts[1] not in _SUFFIXES:
        raise ValueError("ts_code is malformed or unsupported")
    return InstrumentIdentity(_SUFFIXES[parts[1]], parts[0], InstrumentType.EQUITY)


def _date(value: object, field: str, *, optional: bool = False) -> date | None:
    text = "" if value is None else str(value).strip()
    if not text and optional:
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as error:
        raise ValueError(f"{field} is malformed") from error


def _decimal(value: object, field: str, *, optional: bool = False) -> Decimal | None:
    text = "" if value is None else str(value).strip()
    if not text and optional:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"{field} is malformed") from error


def _provenance(
    row: Mapping[str, object], provider_id: str, source: str, identity: str, version: str
) -> DataProvenance:
    return DataProvenance(
        provider_id,
        identity,
        f"tushare://{source}/{identity}",
        None,
        False,
        0,
        raw_payload_hash(row),  # type: ignore[arg-type]
        version,
    )


class TushareAdjustmentFactorNormalizer:
    transformation_version = "tushare-adj-factor/v1"

    def normalize(
        self, row: Mapping[str, object], *, provider_id: str, retrieved_at: datetime
    ) -> AdjustmentFactor:
        instrument = _identity(row.get("ts_code"))
        trading_date = _date(row.get("trade_date"), "trade_date")
        factor = _decimal(row.get("adj_factor"), "adj_factor")
        assert trading_date is not None and factor is not None
        identity = f"{instrument.canonical_key}:{trading_date.isoformat()}"
        return AdjustmentFactor(
            identity,
            instrument,
            trading_date,
            factor,
            "tushare-cumulative/v1",
            retrieved_at,
            _provenance(row, provider_id, "adj_factor", identity, self.transformation_version),
        )


class TushareCorporateActionNormalizer:
    transformation_version = "tushare-dividend/v1"

    def normalize_many(
        self, row: Mapping[str, object], *, provider_id: str, retrieved_at: datetime
    ) -> tuple[CorporateAction, ...]:
        instrument = _identity(row.get("ts_code"))
        record_date = _date(row.get("record_date"), "record_date", optional=True)
        ex_date = _date(row.get("ex_date"), "ex_date", optional=True)
        pay_date = _date(row.get("pay_date"), "pay_date", optional=True)
        effective = ex_date or record_date or _date(row.get("ann_date"), "ann_date", optional=True)
        if effective is None:
            raise ValueError("corporate action requires a dated source fact")
        facts = (
            (
                CorporateActionType.CASH_DIVIDEND,
                _decimal(row.get("cash_div_tax"), "cash_div_tax", optional=True),
                None,
            ),
            (
                CorporateActionType.STOCK_DIVIDEND,
                None,
                _decimal(row.get("stk_bo_rate"), "stk_bo_rate", optional=True),
            ),
            (
                CorporateActionType.CAPITALIZATION,
                None,
                _decimal(row.get("stk_co_rate"), "stk_co_rate", optional=True),
            ),
        )
        results: list[CorporateAction] = []
        for action_type, cash, ratio in facts:
            amount = cash if cash is not None else ratio
            if amount is None or amount == 0:
                continue
            identity = f"{instrument.canonical_key}:{effective}:{action_type.value}"
            results.append(
                CorporateAction(
                    identity,
                    instrument,
                    action_type,
                    record_date,
                    ex_date,
                    pay_date,
                    effective,
                    cash,
                    ratio,
                    None,
                    retrieved_at,
                    _provenance(
                        row, provider_id, "dividend", identity, self.transformation_version
                    ),
                )
            )
        if not results:
            raise ValueError("dividend row contains no implemented corporate action")
        return tuple(results)
