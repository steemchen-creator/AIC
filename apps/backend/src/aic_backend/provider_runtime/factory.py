"""Explicit allowlist Factory for Provider construction."""

from collections.abc import Mapping

from aic_backend.provider_runtime.errors import InvalidProviderDefinitionError
from aic_backend.provider_runtime.interfaces import Provider, ProviderBuilder
from aic_backend.provider_runtime.models import ProviderDefinition


class ProviderFactory:
    """Create providers only through approved implementation builders."""

    def __init__(self, builders: Mapping[str, ProviderBuilder]) -> None:
        self._builders = dict(builders)

    def create(self, definition: ProviderDefinition) -> Provider:
        builder = self._builders.get(definition.implementation)
        if builder is None:
            raise InvalidProviderDefinitionError(
                f"Unknown provider implementation: {definition.implementation}.",
                provider_id=definition.provider_id,
            )
        try:
            provider = builder(definition)
        except Exception as error:
            raise InvalidProviderDefinitionError(
                f"Provider {definition.provider_id} could not be created.",
                provider_id=definition.provider_id,
            ) from error

        metadata = provider.metadata
        if (
            metadata.provider_id != definition.provider_id
            or metadata.enabled != definition.enabled
            or metadata.priority != definition.priority
            or provider.capabilities != definition.capabilities
        ):
            raise InvalidProviderDefinitionError(
                f"Provider {definition.provider_id} does not match its definition.",
                provider_id=definition.provider_id,
            )
        return provider
