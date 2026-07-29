# Domain

## Responsibility

Define immutable, source-neutral data concepts and domain events.

## Boundary

This package uses only the Python standard library. It does not know how data is
transported, retrieved, cached, persisted, or published.

## Prohibited

- FastAPI, Pydantic, SQLAlchemy, Redis, Celery, or provider SDK imports
- HTTP, database, cache, logging, serialization, or dependency injection code
- Vendor-specific or stock-specific concepts

## Future extension

Add typed domain concepts only through approved business tasks. Keep technical
conversion at outer-layer boundaries.
