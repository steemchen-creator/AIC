"""Application-owned ports for Shadow portfolio experiments."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from aic_backend.application.ports.paper import PaperDecisionSource
from aic_backend.domain.experiments import (
    ExperimentManifest,
    GroupTradingSession,
    PerformanceComparisonSnapshot,
    RoleActivity,
)
from aic_backend.domain.paper import (
    ActivatePaperAccount,
    PaperAccount,
    PaperSessionResult,
)
from aic_backend.domain.portfolio.models import Money


@dataclass(frozen=True, slots=True)
class ShadowExperimentRecord:
    manifest: ExperimentManifest
    sessions: tuple[GroupTradingSession, ...] = ()
    comparisons: tuple[PerformanceComparisonSnapshot, ...] = ()
    activities: tuple[RoleActivity, ...] = ()


class ShadowExperimentRepository(Protocol):
    async def save(self, record: ShadowExperimentRecord) -> None: ...

    async def get(self, group_id: str) -> ShadowExperimentRecord | None: ...


class ExperimentPaperRuntime(Protocol):
    async def create_account(
        self,
        display_name: str,
        initial_capital: Money,
        *,
        account_reference: str,
    ) -> PaperAccount: ...

    async def activate(self, command: ActivatePaperAccount) -> PaperAccount: ...

    async def process_session(
        self,
        account_id: str,
        trading_date: date,
        decisions: PaperDecisionSource,
    ) -> PaperSessionResult | None: ...


class ExperimentClock(Protocol):
    def now(self) -> datetime: ...
