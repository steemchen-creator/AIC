"""Exact Decimal conflict detection without reconciliation."""

from aic_backend.data_foundation.quality.models import ConflictValue, DataConflict


class ConflictDetector:
    def detect(
        self,
        record_identity: str,
        field: str,
        values: tuple[ConflictValue, ...],
    ) -> DataConflict | None:
        if len({item.value for item in values}) <= 1:
            return None
        return DataConflict(record_identity, field, values)
