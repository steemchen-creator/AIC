"""Errors raised by market-data domain invariants."""


class DataFoundationError(ValueError):
    """Base error for invalid Data Foundation values."""


class InvalidInstrumentError(DataFoundationError):
    """Raised when an instrument identity is incomplete or malformed."""


class InvalidTimestampError(DataFoundationError):
    """Raised when a timestamp is not timezone-aware."""


class InvalidPayloadError(DataFoundationError):
    """Raised when a payload contains unsupported mutable or opaque values."""


class InvalidProvenanceError(DataFoundationError):
    """Raised when provenance is incomplete or may expose credentials."""
