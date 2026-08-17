"""Tushare instrument master and suspend_d normalization."""

from collections.abc import Mapping
from datetime import date, datetime
from typing import cast

from aic_backend.data_foundation.identity import raw_payload_hash
from aic_backend.domain.market_data import (
    DataProvenance,
    InstrumentIdentity,
    InstrumentMaster,
    InstrumentTradingState,
    InstrumentTradingStatus,
    InstrumentType,
    ListingStatus,
    Market,
)

_MARKETS = {"SSE": Market.CN_SSE, "SZSE": Market.CN_SZSE}
_SUFFIXES = {"SH": Market.CN_SSE, "SZ": Market.CN_SZSE}


def _date(value: object, field: str, *, optional: bool = False) -> date | None:
    text = "" if value is None else str(value).strip()
    if not text and optional:
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as error:
        raise ValueError(f"{field} is malformed") from error


def _identity(ts_code: object, exchange: object | None = None) -> InstrumentIdentity:
    code = str(ts_code).strip().upper()
    try:
        symbol, suffix = code.split(".", 1)
    except ValueError as error:
        raise ValueError("ts_code is malformed") from error
    market = _SUFFIXES.get(suffix)
    if market is None or (exchange is not None and _MARKETS.get(str(exchange)) is not market):
        raise ValueError("instrument exchange is unsupported or inconsistent")
    return InstrumentIdentity(market, symbol, InstrumentType.EQUITY)


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


class TushareInstrumentMasterNormalizer:
    transformation_version = "tushare-stock-basic/v1"

    def normalize(
        self, row: Mapping[str, object], *, provider_id: str, retrieved_at: datetime
    ) -> InstrumentMaster:
        instrument = _identity(row.get("ts_code"), row.get("exchange"))
        statuses = {
            "L": ListingStatus.LISTED,
            "D": ListingStatus.DELISTED,
            "P": ListingStatus.UNKNOWN,
            "G": ListingStatus.UNKNOWN,
        }
        vendor_status = str(row.get("list_status", ""))
        if vendor_status not in statuses:
            raise ValueError("listing status is malformed")
        name = str(row.get("name", "")).strip()
        return InstrumentMaster(
            instrument,
            name,
            _date(row.get("list_date"), "list_date", optional=True),
            _date(row.get("delist_date"), "delist_date", optional=True),
            statuses[vendor_status],
            retrieved_at,
            _provenance(
                row,
                provider_id,
                "stock_basic",
                instrument.canonical_key,
                self.transformation_version,
            ),
        )


class TushareTradingStatusNormalizer:
    transformation_version = "tushare-suspend-d/v1"

    def normalize(
        self, row: Mapping[str, object], *, provider_id: str, retrieved_at: datetime
    ) -> InstrumentTradingStatus:
        instrument = _identity(row.get("ts_code"))
        event_type = str(row.get("suspend_type", ""))
        states = {"S": InstrumentTradingState.SUSPENDED, "R": InstrumentTradingState.TRADING}
        if event_type not in states:
            raise ValueError("suspend_type is malformed")
        trading_date = _date(row.get("trade_date"), "trade_date")
        trading_date = cast(date, trading_date)
        identity = f"{instrument.canonical_key}:{trading_date.isoformat()}"
        return InstrumentTradingStatus(
            instrument,
            trading_date,
            states[event_type],
            str(row.get("suspend_timing", "")).strip() or None,
            retrieved_at,
            _provenance(row, provider_id, "suspend_d", identity, self.transformation_version),
        )
