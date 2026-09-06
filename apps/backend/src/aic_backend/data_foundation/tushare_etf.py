"""Pure Tushare ETF and index normalization with explicit classification evidence."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from math import isfinite
from zoneinfo import ZoneInfo

from aic_backend.data_foundation.identity import deterministic_record_id
from aic_backend.data_foundation.normalization import NormalizationError, NormalizationErrorCode
from aic_backend.domain.market_data import (
    AdjustmentFactor,
    Currency,
    DailyBar,
    DataProvenance,
    ETFChannel,
    ETFInstrumentProfile,
    ETFMasterBundle,
    ETFTracksIndex,
    ETFValuationSnapshot,
    ExposureCategory,
    ExposureFamily,
    ExposureMarket,
    IndexReference,
    InstrumentIdentity,
    InstrumentMaster,
    InstrumentType,
    ListingStatus,
    Market,
    RawObservation,
)

_LISTING_STATUS = {
    "L": ListingStatus.LISTED,
    "D": ListingStatus.DELISTED,
    "P": ListingStatus.UNKNOWN,
}
_ETF_CHANNEL = {"境内": ETFChannel.DOMESTIC, "QDII": ETFChannel.QDII}
_MARKET = {"SH": Market.CN_SSE, "SZ": Market.CN_SZSE}


@dataclass(frozen=True, slots=True)
class ETFClassificationEvidence:
    underlying_market: ExposureMarket
    underlying_currency: Currency
    exposure_category: ExposureCategory
    exposure_family: ExposureFamily = ExposureFamily.UNKNOWN


class _Parser:
    @staticmethod
    def error(field: str, code: NormalizationErrorCode) -> NormalizationError:
        return NormalizationError(code, field, f"Tushare ETF field {field} is invalid.")

    def text(self, row: Mapping[str, object], field: str, *, optional: bool = False) -> str | None:
        value = row.get(field)
        if value is None or not str(value).strip():
            if optional:
                return None
            raise self.error(field, NormalizationErrorCode.MISSING_FIELD)
        return str(value).strip()

    def decimal(
        self, row: Mapping[str, object], field: str, *, optional: bool = False
    ) -> Decimal | None:
        value = row.get(field)
        if value is None or str(value).strip() == "":
            if optional:
                return None
            raise self.error(field, NormalizationErrorCode.MISSING_FIELD)
        if isinstance(value, bool) or isinstance(value, float) and not isfinite(value):
            raise self.error(field, NormalizationErrorCode.INVALID_VALUE)
        try:
            parsed = Decimal(str(value))
        except InvalidOperation:
            raise self.error(field, NormalizationErrorCode.INVALID_VALUE) from None
        if not parsed.is_finite():
            raise self.error(field, NormalizationErrorCode.INVALID_VALUE)
        return parsed

    def date(self, row: Mapping[str, object], field: str, *, optional: bool = False) -> date | None:
        value = self.text(row, field, optional=optional)
        if value is None:
            return None
        try:
            return datetime.strptime(value, "%Y%m%d").date()
        except ValueError:
            raise self.error(field, NormalizationErrorCode.INVALID_VALUE) from None

    def row(self, observation: RawObservation, capability: str) -> Mapping[str, object]:
        if observation.capability.value != capability:
            raise self.error("capability", NormalizationErrorCode.UNSUPPORTED_RECORD)
        if not isinstance(observation.payload, Mapping):
            raise self.error("payload", NormalizationErrorCode.INVALID_TYPE)
        return observation.payload


def _etf_identity(code: str) -> InstrumentIdentity:
    symbol, separator, suffix = code.strip().upper().partition(".")
    if not separator or not symbol or suffix not in _MARKET:
        raise _Parser.error("ts_code", NormalizationErrorCode.UNSUPPORTED_RECORD)
    return InstrumentIdentity(_MARKET[suffix], symbol, InstrumentType.ETF)


def _index_identity(code: str) -> InstrumentIdentity:
    normalized = code.strip().upper()
    if not normalized:
        raise _Parser.error("index_code", NormalizationErrorCode.INVALID_VALUE)
    return InstrumentIdentity(
        Market.INDEX_REFERENCE,
        normalized.replace(".", "-"),
        InstrumentType.INDEX,
    )


def _event_time(trading_date: date) -> datetime:
    return datetime.combine(trading_date, time(15), ZoneInfo("Asia/Shanghai")).astimezone(UTC)


def _provenance(
    observation: RawObservation, source: str, source_id: str, version: str
) -> DataProvenance:
    failover = observation.source_metadata.get("failover_count", 0)
    if not isinstance(failover, int) or isinstance(failover, bool) or failover < 0:
        raise _Parser.error("failover_count", NormalizationErrorCode.INVALID_TYPE)
    timestamp = observation.source_metadata.get("provider_timestamp")
    if timestamp is not None and not isinstance(timestamp, datetime):
        raise _Parser.error("provider_timestamp", NormalizationErrorCode.INVALID_TYPE)
    return DataProvenance(
        observation.provider_id,
        source_id,
        f"tushare://{source}/{source_id}",
        timestamp,
        failover > 0,
        failover,
        observation.payload_hash,
        version,
    )


class TushareETFMasterNormalizer(_Parser):
    transformation_version = "tushare-etf-basic/v1"

    def __init__(
        self, classifications: Mapping[str, ETFClassificationEvidence] | None = None
    ) -> None:
        self._classifications = dict(classifications or {})

    def normalize(self, observation: RawObservation) -> ETFMasterBundle:
        row = self.row(observation, "ETF_INSTRUMENT_MASTER")
        code = self.text(row, "ts_code")
        assert code is not None
        instrument = _etf_identity(code)
        status_code = self.text(row, "list_status")
        channel_code = self.text(row, "etf_type")
        if status_code not in _LISTING_STATUS:
            raise self.error("list_status", NormalizationErrorCode.INVALID_VALUE)
        channel = _ETF_CHANNEL.get(channel_code or "", ETFChannel.UNKNOWN)
        classification = self._classifications.get(
            code,
            ETFClassificationEvidence(
                ExposureMarket.UNKNOWN, Currency.UNKNOWN, ExposureCategory.UNKNOWN
            ),
        )
        display_name = self.text(row, "csname")
        assert display_name is not None
        benchmark_code = self.text(row, "index_code", optional=True)
        benchmark = None if benchmark_code is None else _index_identity(benchmark_code)
        listing_date = self.date(row, "list_date", optional=True)
        delisting_date = self.date(row, "delist_date", optional=True)
        provenance = _provenance(
            observation, "etf_basic", instrument.canonical_key, self.transformation_version
        )
        master = InstrumentMaster(
            instrument,
            display_name,
            listing_date,
            delisting_date,
            _LISTING_STATUS[status_code],
            observation.received_at,
            provenance,
        )
        profile = ETFInstrumentProfile(
            instrument,
            display_name,
            self.text(row, "extname", optional=True),
            listing_date,
            delisting_date,
            _LISTING_STATUS[status_code],
            channel,
            benchmark,
            self.text(row, "mgr_name", optional=True),
            self.decimal(row, "mgt_fee", optional=True),
            classification.underlying_market,
            classification.underlying_currency,
            Currency.CNY,
            classification.exposure_category,
            provenance,
            observation.received_at,
            classification.exposure_family,
        )
        relationship = None
        if benchmark is not None:
            relationship = ETFTracksIndex(
                f"{instrument.canonical_key}:{benchmark.canonical_key}:current",
                instrument,
                benchmark,
                None,
                None,
                True,
                provenance,
                observation.received_at,
            )
        return ETFMasterBundle(master, profile, relationship)


class TushareIndexReferenceNormalizer(_Parser):
    transformation_version = "tushare-etf-index/v1"

    def __init__(
        self,
        classifications: Mapping[str, tuple[ExposureMarket, Currency]] | None = None,
    ) -> None:
        self._classifications = dict(classifications or {})

    def normalize(self, observation: RawObservation) -> IndexReference:
        row = self.row(observation, "INDEX_REFERENCE")
        code = self.text(row, "ts_code")
        name = self.text(row, "indx_name")
        assert code is not None and name is not None
        identity = _index_identity(code)
        exposure, currency = self._classifications.get(
            code, (ExposureMarket.UNKNOWN, Currency.UNKNOWN)
        )
        return IndexReference(
            identity,
            name,
            self.text(row, "pub_party_name", optional=True),
            self.date(row, "base_date", optional=True),
            self.decimal(row, "bp", optional=True),
            exposure,
            currency,
            _provenance(
                observation,
                "etf_index",
                identity.canonical_key,
                self.transformation_version,
            ),
            observation.received_at,
        )


class TushareETFDailyBarNormalizer(_Parser):
    transformation_version = "tushare-etf-daily/v1"

    def normalize(self, observation: RawObservation) -> DailyBar:
        row = self.row(observation, "ETF_DAILY_BAR")
        code = self.text(row, "ts_code")
        trading_date = self.date(row, "trade_date")
        assert code is not None and trading_date is not None
        instrument = _etf_identity(code)
        event_time = _event_time(trading_date)
        volume_lots = self.decimal(row, "vol")
        amount_thousands = self.decimal(row, "amount")
        assert volume_lots is not None and amount_thousands is not None
        volume_units = volume_lots * 100
        if volume_units != volume_units.to_integral_value():
            raise self.error("vol", NormalizationErrorCode.INVALID_VALUE)
        values = tuple(self.decimal(row, field) for field in ("open", "high", "low", "close"))
        assert all(value is not None for value in values)
        return DailyBar(
            deterministic_record_id(
                instrument,
                DailyBar.RECORD_TYPE,
                event_time,
                trading_date.isoformat(),
            ),
            "1.0",
            instrument,
            trading_date,
            event_time,
            observation.received_at,
            observation.received_at,
            _provenance(
                observation,
                "fund_daily",
                f"{code}:{trading_date.isoformat()}",
                self.transformation_version,
            ),
            values[0],  # type: ignore[arg-type]
            values[1],  # type: ignore[arg-type]
            values[2],  # type: ignore[arg-type]
            values[3],  # type: ignore[arg-type]
            int(volume_units),
            amount_thousands * 1000,
        )


class TushareETFAdjustmentFactorNormalizer(_Parser):
    transformation_version = "tushare-etf-adjustment-factor/v1"

    def normalize(self, observation: RawObservation) -> AdjustmentFactor:
        row = self.row(observation, "ETF_ADJUSTMENT_FACTOR")
        code = self.text(row, "ts_code")
        trading_date = self.date(row, "trade_date")
        factor = self.decimal(row, "adj_factor")
        assert code is not None and trading_date is not None and factor is not None
        instrument = _etf_identity(code)
        identity = f"{instrument.canonical_key}:{trading_date.isoformat()}"
        return AdjustmentFactor(
            f"etf-factor:{identity}",
            instrument,
            trading_date,
            factor,
            self.transformation_version,
            observation.received_at,
            _provenance(observation, "fund_adj", identity, self.transformation_version),
        )


class TushareETFValuationNormalizer(_Parser):
    transformation_version = "tushare-etf-share-size/v1"

    def normalize(self, observation: RawObservation) -> ETFValuationSnapshot:
        row = self.row(observation, "ETF_VALUATION")
        code = self.text(row, "ts_code")
        trading_date = self.date(row, "trade_date")
        assert code is not None and trading_date is not None
        instrument = _etf_identity(code)
        nav = self.decimal(row, "nav", optional=True)
        close = self.decimal(row, "close", optional=True)
        total_share = self.decimal(row, "total_share", optional=True)
        premium = None if nav is None or close is None else (close - nav) / nav * 100
        identity = f"{instrument.canonical_key}:{trading_date.isoformat()}"
        return ETFValuationSnapshot(
            f"etf-valuation:{identity}",
            instrument,
            trading_date,
            nav,
            close,
            None if total_share is None else total_share * 10000,
            premium,
            _provenance(observation, "etf_share_size", identity, self.transformation_version),
            observation.received_at,
        )


class TushareIndexDailyBarNormalizer(_Parser):
    transformation_version = "tushare-index-daily/v1"

    def normalize(self, observation: RawObservation) -> DailyBar:
        row = self.row(observation, "INDEX_DAILY_BAR")
        code = self.text(row, "ts_code")
        trading_date = self.date(row, "trade_date")
        assert code is not None and trading_date is not None
        instrument = _index_identity(code)
        event_time = _event_time(trading_date)
        volume_lots = self.decimal(row, "vol")
        amount_thousands = self.decimal(row, "amount")
        assert volume_lots is not None and amount_thousands is not None
        volume = volume_lots * 100
        if volume != volume.to_integral_value():
            raise self.error("vol", NormalizationErrorCode.INVALID_VALUE)
        prices = tuple(self.decimal(row, field) for field in ("open", "high", "low", "close"))
        assert all(value is not None for value in prices)
        return DailyBar(
            deterministic_record_id(
                instrument,
                DailyBar.RECORD_TYPE,
                event_time,
                trading_date.isoformat(),
            ),
            "1.0",
            instrument,
            trading_date,
            event_time,
            observation.received_at,
            observation.received_at,
            _provenance(
                observation,
                "index_daily",
                f"{code}:{trading_date.isoformat()}",
                self.transformation_version,
            ),
            prices[0],  # type: ignore[arg-type]
            prices[1],  # type: ignore[arg-type]
            prices[2],  # type: ignore[arg-type]
            prices[3],  # type: ignore[arg-type]
            int(volume),
            amount_thousands * 1000,
        )
