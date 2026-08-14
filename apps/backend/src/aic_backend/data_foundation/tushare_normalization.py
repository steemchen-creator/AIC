"""Pure Tushare A-share daily row normalization."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from math import isfinite
from zoneinfo import ZoneInfo

from aic_backend.data_foundation.identity import deterministic_record_id
from aic_backend.data_foundation.normalization import NormalizationError, NormalizationErrorCode
from aic_backend.domain.market_data import (
    DailyBar,
    DataProvenance,
    InstrumentIdentity,
    InstrumentType,
    Market,
    RawObservation,
)


class TushareDailyBarNormalizer:
    transformation_version = "tushare-daily-bar/v1"

    def normalize(self, observation: RawObservation) -> DailyBar:
        row = observation.payload
        if not isinstance(row, Mapping):
            raise self._error("payload", NormalizationErrorCode.INVALID_TYPE)
        code = self._text(row, "ts_code")
        symbol, separator, exchange = code.partition(".")
        markets = {"SH": Market.CN_SSE, "SZ": Market.CN_SZSE}
        if not separator or exchange not in markets:
            raise self._error("ts_code", NormalizationErrorCode.UNSUPPORTED_RECORD)
        trading_date = self._date(row, "trade_date")
        event_time = datetime.combine(
            trading_date, time(15), ZoneInfo("Asia/Shanghai")
        ).astimezone(UTC)
        instrument = InstrumentIdentity(markets[exchange], symbol, InstrumentType.EQUITY)
        failover_count = observation.source_metadata.get("failover_count", 0)
        if (
            not isinstance(failover_count, int)
            or isinstance(failover_count, bool)
            or failover_count < 0
        ):
            raise self._error("failover_count", NormalizationErrorCode.INVALID_TYPE)
        provenance = DataProvenance(
            observation.provider_id, code + ":" + trading_date.isoformat(),
            "tushare://daily/" + code, None, failover_count > 0, failover_count,
            observation.payload_hash,
            self.transformation_version,
        )
        record_id = deterministic_record_id(
            instrument, DailyBar.RECORD_TYPE, event_time, trading_date.isoformat()
        )
        volume_lots = self._decimal(row, "vol")
        volume_shares = volume_lots * 100
        if volume_shares != volume_shares.to_integral_value():
            raise self._error("vol", NormalizationErrorCode.INVALID_VALUE)
        return DailyBar(
            record_id, "1.0", instrument, trading_date, event_time,
            observation.received_at, observation.received_at, provenance,
            self._decimal(row, "open"), self._decimal(row, "high"),
            self._decimal(row, "low"), self._decimal(row, "close"),
            int(volume_shares), self._decimal(row, "amount") * 1000,
        )

    @staticmethod
    def _error(field: str, code: NormalizationErrorCode) -> NormalizationError:
        return NormalizationError(code, field, f"Tushare field {field} is invalid.")

    def _text(self, row: Mapping[str, object], field: str) -> str:
        if field not in row:
            raise self._error(field, NormalizationErrorCode.MISSING_FIELD)
        value = row[field]
        if not isinstance(value, str) or not value.strip():
            raise self._error(field, NormalizationErrorCode.INVALID_TYPE)
        return value.strip()

    def _decimal(self, row: Mapping[str, object], field: str) -> Decimal:
        value = row.get(field)
        if value is None or isinstance(value, bool):
            raise self._error(field, NormalizationErrorCode.INVALID_TYPE)
        if isinstance(value, float) and not isfinite(value):
            raise self._error(field, NormalizationErrorCode.INVALID_VALUE)
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise self._error(field, NormalizationErrorCode.INVALID_VALUE) from None
        if not parsed.is_finite():
            raise self._error(field, NormalizationErrorCode.INVALID_VALUE)
        return parsed

    def _date(self, row: Mapping[str, object], field: str) -> date:
        try:
            return datetime.strptime(self._text(row, field), "%Y%m%d").date()
        except ValueError:
            raise self._error(field, NormalizationErrorCode.INVALID_VALUE) from None
