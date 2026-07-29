# Presentation

## Responsibility

Translate HTTP requests and responses and invoke Application use cases.

## Boundary

Presentation receives configured use cases through bootstrap wiring.

## Prohibited

- Direct provider, repository, cache, event bus, database, or Redis access
- Business decisions or vendor response parsing

## Future extension

Add transport-specific endpoints around approved Application use cases. Keep Pydantic and FastAPI types within this package.
