"""Deterministic identity and raw-payload hashing."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from aic_backend.domain.market_data import InstrumentIdentity, InvalidPayloadError
from aic_backend.domain.market_data.models import InputValue, RawPayload


def _json_value(value: InputValue) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvalidPayloadError("raw payload datetime must include timezone information")
        return {"$datetime": value.astimezone(UTC).isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) or not key for key in value):
            raise InvalidPayloadError("raw payload keys must be non-empty strings")
        return {key: _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    raise InvalidPayloadError("raw payload contains unsupported value type")


def raw_payload_hash(payload: RawPayload) -> str:
    """Return a type-delimited SHA-256 hash with canonical mapping serialization."""
    if isinstance(payload, bytes):
        encoded = b"bytes:\x00" + payload
    elif isinstance(payload, str):
        encoded = b"text:\x00" + payload.encode("utf-8")
    elif isinstance(payload, Mapping):
        normalized = _json_value(payload)
        encoded = b"mapping:\x00" + json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    else:
        raise InvalidPayloadError("raw payload must be bytes, text, or a mapping")
    return hashlib.sha256(encoded).hexdigest()


def deterministic_record_id(
    instrument: InstrumentIdentity,
    record_type: str,
    event_time: datetime,
    discriminator: str = "",
) -> str:
    """Derive a stable ID from the logical financial-fact identity."""
    normalized_type = record_type.strip().upper()
    if not normalized_type:
        raise ValueError("record_type must not be empty")
    if event_time.tzinfo is None or event_time.utcoffset() is None:
        raise ValueError("event_time must include timezone information")
    identity: dict[str, Any] = {
        "discriminator": discriminator,
        "event_time": event_time.astimezone(UTC).isoformat(),
        "instrument": instrument.canonical_key,
        "instrument_type": instrument.instrument_type.value,
        "record_type": normalized_type,
        "version": 1,
    }
    encoded = json.dumps(identity, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"rec_{hashlib.sha256(encoded).hexdigest()}"
