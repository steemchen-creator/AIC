"""Framework-independent data foundation domain."""

from aic_backend.domain.events import DataRecordReceived
from aic_backend.domain.models import DataRecord

__all__ = ["DataRecord", "DataRecordReceived"]
