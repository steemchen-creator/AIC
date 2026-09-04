"""Application-owned persistence contract for execution and risk evidence."""

from typing import Protocol

from aic_backend.domain.execution import ExecutionOutcome, RiskDecision


class ExecutionEvidenceRepository(Protocol):
    async def save(self, outcome: ExecutionOutcome) -> None: ...

    async def get_risk_decision(self, risk_decision_id: str) -> RiskDecision | None: ...
