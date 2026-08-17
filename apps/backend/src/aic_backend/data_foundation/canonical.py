"""Phase 1 construction helpers for immutable observations."""

from collections.abc import Mapping
from datetime import datetime

from aic_backend.data_foundation.identity import raw_payload_hash
from aic_backend.domain.market_data import DataCapability, RawObservation
from aic_backend.domain.market_data.models import InputValue, RawPayload


def create_raw_observation(
    *,
    observation_id: str,
    provider_id: str,
    capability: DataCapability,
    received_at: datetime,
    payload: RawPayload,
    source_metadata: Mapping[str, InputValue],
) -> RawObservation:
    return RawObservation(
        observation_id=observation_id,
        provider_id=provider_id,
        capability=capability,
        received_at=received_at,
        payload=payload,
        payload_hash=raw_payload_hash(payload),
        source_metadata=source_metadata,
    )
