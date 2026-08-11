"""Stable errors exposed by the provider runtime boundary."""


class ProviderRuntimeError(Exception):
    """Base error carrying safe, auditable invocation context."""

    error_code = "PROVIDER_RUNTIME_ERROR"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        request_id: str | None = None,
        provider_id: str | None = None,
        capability: str | None = None,
        failover_occurred: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.request_id = request_id
        self.provider_id = provider_id
        self.capability = capability
        self.failover_occurred = failover_occurred


class ProviderRegistrationError(ProviderRuntimeError):
    error_code = "PROVIDER_REGISTRATION_ERROR"


class DuplicateProviderError(ProviderRegistrationError):
    error_code = "PROVIDER_DUPLICATE"


class ProviderNotFoundError(ProviderRegistrationError):
    error_code = "PROVIDER_NOT_FOUND"


class InvalidProviderDefinitionError(ProviderRegistrationError):
    error_code = "PROVIDER_DEFINITION_INVALID"


class ProviderLifecycleError(ProviderRuntimeError):
    error_code = "PROVIDER_LIFECYCLE_ERROR"


class InvalidStateTransitionError(ProviderLifecycleError):
    error_code = "PROVIDER_STATE_TRANSITION_INVALID"


class ProviderSelectionError(ProviderRuntimeError):
    error_code = "PROVIDER_SELECTION_ERROR"

    def __init__(
        self,
        message: str,
        *,
        supported_provider_count: int = 0,
        exclusion_summary: dict[str, str] | None = None,
        request_id: str | None = None,
        provider_id: str | None = None,
        capability: str | None = None,
        failover_occurred: bool = False,
    ) -> None:
        super().__init__(
            message,
            request_id=request_id,
            provider_id=provider_id,
            capability=capability,
            failover_occurred=failover_occurred,
        )
        self.supported_provider_count = supported_provider_count
        self.exclusion_summary = dict(exclusion_summary or {})


class NoProviderAvailableError(ProviderSelectionError):
    error_code = "PROVIDER_NO_AVAILABLE"
    retryable = True


class CapabilityUnavailableError(ProviderSelectionError):
    error_code = "PROVIDER_CAPABILITY_UNAVAILABLE"


class InvalidSelectionContextError(ProviderSelectionError):
    error_code = "PROVIDER_SELECTION_CONTEXT_INVALID"


class ProviderInvocationError(ProviderRuntimeError):
    error_code = "PROVIDER_INVOCATION_ERROR"


class ProviderExecutionError(ProviderInvocationError):
    error_code = "PROVIDER_EXECUTION_ERROR"


class ProviderCancelledError(ProviderInvocationError):
    error_code = "PROVIDER_CANCELLED"


class ProviderTimeoutError(ProviderInvocationError):
    error_code = "PROVIDER_TIMEOUT"
    retryable = True


class ProviderUnavailableError(ProviderInvocationError):
    error_code = "PROVIDER_UNAVAILABLE"
    retryable = True


class ProviderRateLimitedError(ProviderInvocationError):
    error_code = "PROVIDER_RATE_LIMITED"
    retryable = True


class ProviderTransientError(ProviderInvocationError):
    error_code = "PROVIDER_TRANSIENT"
    retryable = True


class ProviderPermanentError(ProviderInvocationError):
    error_code = "PROVIDER_PERMANENT"


class ProviderInvalidResponseError(ProviderInvocationError):
    error_code = "PROVIDER_RESPONSE_INVALID"


class InvalidRequestError(ProviderInvocationError):
    error_code = "PROVIDER_REQUEST_INVALID"


class AuthenticationConfigurationError(ProviderInvocationError):
    error_code = "PROVIDER_AUTH_CONFIGURATION"


class CapabilityNotSupportedError(ProviderInvocationError):
    error_code = "PROVIDER_CAPABILITY_NOT_SUPPORTED"


class UserPermissionError(ProviderInvocationError):
    error_code = "PROVIDER_PERMISSION_DENIED"


class AllProvidersFailedError(ProviderInvocationError):
    error_code = "PROVIDER_ALL_FAILED"
    retryable = True
