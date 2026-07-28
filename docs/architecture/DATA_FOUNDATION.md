# Data Foundation Architecture

## Purpose

Data Foundation provides one framework-independent path for obtaining, storing,
caching, and announcing data. It is intentionally data-source neutral in
TASK-002: no market, financial, news, AI, strategy, or portfolio behavior is
implemented.

## Layers and dependency direction

```text
presentation -> application -> domain
                    ^
                    |
        providers and infrastructure
```

- `presentation` owns HTTP request and response concerns.
- `application` coordinates use cases and owns outbound port contracts.
- `domain` owns immutable data concepts and has no third-party dependencies.
- `providers` obtain data and implement an application provider port.
- `infrastructure` supplies repository, cache, event bus, and operational
  adapters through application ports.
- `bootstrap` is the composition root and is the only package that wires
  concrete adapters to use cases.
- `shared` contains technical configuration and logging used by outer layers.

Dependencies must point inward. Presentation never accesses providers,
databases, caches, or event buses directly. Domain never imports FastAPI,
Pydantic, SQLAlchemy, Redis, Celery, or any other framework.

## Data flow

The read use case follows one deterministic path:

1. Read from cache.
2. If absent, read from the repository.
3. If absent, request the configured provider.
4. Persist provider data through the repository.
5. Cache the result.
6. Publish a domain event.
7. Return the domain object to presentation.

The application layer coordinates these responsibilities without knowing the
concrete implementation of any adapter.

## TASK-002 implementation boundary

TASK-002 uses only deterministic in-memory adapters and a mock provider. These
prove replaceability without introducing database schemas, migrations, live
services, credentials, retries, or vendor behavior. The existing PostgreSQL and
Redis startup checks remain operational foundation concerns and are not used by
the data use case in this checkpoint.

## Migration and rollback

The backend import root moves to `apps/backend/src/aic_backend`. Docker, tests,
and CI install this package through `pyproject.toml`; the HTTP behavior from
Checkpoint 1 remains compatible. Rollback is a revert of the TASK-002 commits;
there is no database or persisted-data migration.
