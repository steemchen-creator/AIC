"""Tushare trade_cal row normalization and minimal calendar validation."""

from collections.abc import Mapping
from datetime import datetime

from aic_backend.data_foundation.identity import raw_payload_hash
from aic_backend.domain.market_data import (
    DataProvenance,
    Market,
    TradingSessionDay,
    standard_a_share_session,
)


class TushareCalendarNormalizer:
    transformation_version = "tushare-trade-cal/v1"

    def normalize(
        self, row: Mapping[str, object], *, provider_id: str, retrieved_at: datetime
    ) -> TradingSessionDay:
        exchange = row.get("exchange")
        markets = {"SSE": Market.CN_SSE, "SZSE": Market.CN_SZSE}
        if exchange not in markets:
            raise ValueError("calendar exchange is unsupported")
        try:
            trading_date = datetime.strptime(str(row["cal_date"]), "%Y%m%d").date()
        except (KeyError, ValueError) as error:
            raise ValueError("calendar date is malformed") from error
        flag = str(row.get("is_open", ""))
        if flag not in {"0", "1"}:
            raise ValueError("calendar open flag is malformed")
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include timezone information")
        digest = raw_payload_hash(row)  # type: ignore[arg-type]
        provenance = DataProvenance(
            provider_id,
            f"{exchange}:{trading_date.isoformat()}",
            f"tushare://trade_cal/{exchange}/{trading_date.isoformat()}",
            None,
            False,
            0,
            digest,
            self.transformation_version,
        )
        is_open = flag == "1"
        return TradingSessionDay(
            markets[exchange],
            trading_date,
            is_open,
            standard_a_share_session(trading_date) if is_open else None,
            retrieved_at,
            provenance,
        )
