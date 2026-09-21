"""Pure normalization and deterministic revision linking for macro observations."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation

from aic_backend.domain.evidence import (
    MacroFrequency,
    MacroObservation,
    MacroSeriesIdentity,
    SeasonalAdjustment,
)
from aic_backend.domain.market_data import AuthorityLevel, SourceLineage, SourceType

_FREQUENCIES = {
    "D": MacroFrequency.DAILY,
    "W": MacroFrequency.WEEKLY,
    "M": MacroFrequency.MONTHLY,
    "Q": MacroFrequency.QUARTERLY,
    "A": MacroFrequency.ANNUAL,
}
_ADJUSTMENTS = {
    "NSA": SeasonalAdjustment.NOT_SEASONALLY_ADJUSTED,
    "SA": SeasonalAdjustment.SEASONALLY_ADJUSTED,
    "SAAR": SeasonalAdjustment.SEASONALLY_ADJUSTED_ANNUAL_RATE,
    "NA": SeasonalAdjustment.NOT_APPLICABLE,
}


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(_required_text(value, field))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO date") from error


def _release_at(value: object) -> datetime:
    return datetime.combine(_date(value, "release_at"), time.max, tzinfo=UTC)


class MacroNormalizer:
    transformation_version = "macro-canonical/v1"

    def normalize_fred(
        self,
        payload: Mapping[str, object],
        *,
        adapter_id: str,
        observed_at: datetime,
        ingested_at: datetime,
        raw_hash: str,
    ) -> tuple[MacroSeriesIdentity, tuple[MacroObservation, ...]]:
        series_value, rows_value = payload.get("series"), payload.get("observations")
        if not isinstance(series_value, Mapping) or not isinstance(rows_value, Sequence):
            raise ValueError("macro payload requires series and observations")
        series_id = _required_text(series_value.get("series_id"), "series_id")
        try:
            frequency = _FREQUENCIES[_required_text(series_value.get("frequency"), "frequency")]
            adjustment = _ADJUSTMENTS[
                _required_text(series_value.get("seasonal_adjustment"), "seasonal_adjustment")
            ]
        except KeyError as error:
            raise ValueError("unsupported macro frequency or seasonal adjustment") from error
        series = MacroSeriesIdentity(
            series_id,
            _required_text(series_value.get("title"), "title"),
            _required_text(series_value.get("geography"), "geography"),
            _required_text(series_value.get("source_agency_id"), "source_agency_id"),
            _required_text(series_value.get("unit"), "unit"),
            frequency,
            adjustment,
        )
        ordered: list[tuple[date, date, Mapping[str, object]]] = []
        for row in rows_value:
            if not isinstance(row, Mapping):
                raise ValueError("macro observation must be a mapping")
            ordered.append(
                (
                    _date(row.get("date"), "date"),
                    _date(row.get("realtime_start"), "realtime_start"),
                    row,
                )
            )
        ordered.sort(key=lambda item: (item[0], item[1], json.dumps(dict(item[2]), sort_keys=True)))
        previous: dict[date, str] = {}
        observations: list[MacroObservation] = []
        for period, realtime_start, row in ordered:
            raw_value = _required_text(row.get("value"), "value")
            if raw_value == ".":
                continue
            try:
                value = Decimal(raw_value)
            except InvalidOperation as error:
                raise ValueError("macro value must be decimal text") from error
            realtime_end = _date(row.get("realtime_end"), "realtime_end")
            observation_id = (
                "macro_"
                + hashlib.sha256(
                    f"{series_id}:{period}:{realtime_start}:{raw_hash}".encode()
                ).hexdigest()
            )
            release_at = _release_at(row.get("release_at", realtime_start.isoformat()))
            lineage = SourceLineage(
                adapter_id,
                "FRED_ALFRED",
                AuthorityLevel.PRIMARY,
                SourceType.OFFICIAL_API,
                datetime.combine(period, time.min, tzinfo=UTC),
                observed_at,
                ingested_at,
                raw_hash,
                self.transformation_version,
                published_at=release_at,
                source_uri="https://api.stlouisfed.org/fred/series/observations",
                source_record_id=f"{series_id}:{period}:{realtime_start}",
            )
            observations.append(
                MacroObservation(
                    observation_id,
                    series,
                    period,
                    period,
                    value,
                    release_at,
                    realtime_start,
                    realtime_end,
                    realtime_start,
                    observed_at,
                    ingested_at,
                    lineage,
                    previous.get(period),
                )
            )
            previous[period] = observation_id
        return series, tuple(observations)
