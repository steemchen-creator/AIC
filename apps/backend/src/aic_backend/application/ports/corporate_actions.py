"""Application-owned corporate-action and adjustment persistence contracts."""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Protocol

from aic_backend.application.ports.historical import BackfillMetadataRepository
from aic_backend.application.ports.persistence import SaveResult
from aic_backend.domain.market_data.corporate_actions import (
    AdjustmentFactor,
    CorporateAction,
)
from aic_backend.domain.market_data.models import InstrumentIdentity


class AdjustmentFactorRepository(Protocol):
    async def save(self, value: AdjustmentFactor) -> SaveResult: ...
    async def get_adjustment_factor(
        self, instrument: InstrumentIdentity, trading_date: date
    ) -> AdjustmentFactor | None: ...
    async def list_adjustment_factors(
        self, instrument: InstrumentIdentity, start: date, end: date
    ) -> tuple[AdjustmentFactor, ...]: ...


class CorporateActionRepository(Protocol):
    async def save(self, value: CorporateAction) -> SaveResult: ...
    async def get_corporate_action(self, action_id: str) -> CorporateAction | None: ...
    async def list_corporate_actions(
        self, instrument: InstrumentIdentity, start: date, end: date
    ) -> tuple[CorporateAction, ...]: ...


AdjustmentCoverageRepository = BackfillMetadataRepository


class AdjustmentFactorNormalizer(Protocol):
    def normalize(
        self, payload: Mapping[str, object], *, provider_id: str, retrieved_at: datetime
    ) -> AdjustmentFactor: ...


class CorporateActionNormalizer(Protocol):
    def normalize_many(
        self, payload: Mapping[str, object], *, provider_id: str, retrieved_at: datetime
    ) -> tuple[CorporateAction, ...]: ...
