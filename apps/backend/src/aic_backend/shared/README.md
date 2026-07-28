# Shared

## Responsibility

Provide technical configuration, logging, and common operational exceptions to outer backend layers.

## Boundary

Shared is not Domain. Domain does not import this package. Settings may use framework libraries because they are consumed only by bootstrap and infrastructure.

## Prohibited

- Domain models, use cases, provider behavior, or persistence decisions
- Secrets or environment-specific values in source control

## Future extension

Add a shared technical utility only when at least two outer layers require the same stable behavior.
