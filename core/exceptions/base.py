class AICError(Exception):
    """Base exception for expected AIC application errors."""


class ConfigurationError(AICError):
    """Raised when required application configuration is missing or invalid."""
