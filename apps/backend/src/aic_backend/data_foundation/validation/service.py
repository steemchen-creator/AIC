"""Explicit, non-reflective dispatch for supported canonical record types."""

from aic_backend.data_foundation.validation.models import ValidationResult, Validator
from aic_backend.domain.market_data import CanonicalRecord, DailyBar


class DataValidationService:
    def __init__(
        self,
        canonical_validator: Validator[CanonicalRecord],
        daily_bar_validator: Validator[DailyBar],
    ) -> None:
        self._canonical_validator = canonical_validator
        self._daily_bar_validator = daily_bar_validator

    def validate(self, record: object) -> ValidationResult:
        if isinstance(record, DailyBar):
            return self._daily_bar_validator.validate(record)
        if isinstance(record, CanonicalRecord):
            return self._canonical_validator.validate(record)
        raise TypeError(f"No validator registered for {type(record).__name__}.")
