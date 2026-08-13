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

Automated dependency rules additionally enforce that Domain cannot depend on
Application, Providers and Infrastructure cannot depend on Presentation,
Presentation cannot depend on Bootstrap, and Application cannot import concrete
adapters. Bootstrap is the only package allowed to reference Application and
concrete adapters together.

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

Mock fixture values live outside the composition root in
`providers/fixtures.py`. `build_container()` is limited to selecting and wiring
the Provider, Repository, Cache, Event Bus, and use case.

## Health semantics

`GET /health` is a liveness endpoint: a successful response means that the
application process can serve HTTP. PostgreSQL and Redis are verified once
during application startup when `AIC_VERIFY_DEPENDENCIES=true`. `/health` does
not perform a live dependency probe and must not be interpreted as one.

## Migration and rollback

The backend import root moves to `apps/backend/src/aic_backend`. Docker, tests,
and CI install this package through `pyproject.toml`; the HTTP behavior from
Checkpoint 1 remains compatible. Rollback is a revert of the TASK-002 commits;
there is no database or persisted-data migration.

## SPEC-004 Phase 1: real-data domain foundation

SPEC-004 extends, rather than replaces, the TASK-002 boundary. The compatibility
`DataRecord` remains unchanged. New source-neutral types live under
`domain/market_data`, while deterministic hashing and construction helpers live under
`data_foundation`:

```text
domain/market_data/
|-- enums.py       market, instrument-type and data-capability codes
|-- errors.py      stable invariant failures
|-- models.py      instrument, provenance, raw, canonical and DailyBar values
`-- __init__.py    public domain surface

data_foundation/
|-- identity.py    deterministic record ID and canonical raw hashing
|-- canonical.py   Raw Observation construction
`-- __init__.py    public helper surface
```

Domain remains standard-library-only and does not depend on Provider Runtime.
`data_foundation` may depend inward on market-data Domain but not on FastAPI,
Infrastructure, Provider Runtime, network or database code.

### Identity and time

An instrument is identified by market, symbol and instrument type. The canonical key
uses the market-qualified form such as `CN.SSE.600519`; the type is retained in the
record identity input. A record ID is SHA-256 over a versioned canonical serialization
of instrument key/type, record type, UTC event time and a domain discriminator.

`event_time`, `observed_at` and `ingested_at` are independent, timezone-aware values
normalized to UTC. `DailyBar.trading_date` retains the source market's calendar date
and is not inferred from UTC.

### Immutability and provenance

Models are frozen, slotted dataclasses. Mappings are recursively copied and exposed as
immutable mappings; sequences become tuples. Unsupported opaque payload objects are
rejected. Raw payload hashes use type-delimited SHA-256 and canonical key ordering.

Every canonical value carries Provider ID, optional source ID/URI/timestamp, failover
attribution, raw hash and transformation version. Credentials are not model fields,
and source URIs containing user information or common secret query keys are rejected.

### Deferred capabilities

Validation, quality scoring, conflict handling, normalization, ingestion, repository
ports, persistence and real Provider integration are deferred to reviewed later phases.
The Phase 1 `CanonicalRecord` therefore does not pretend that a Phase 3 quality
assessment already exists.

## SPEC-004 Phase 2: Validation Engine

The Validation Engine is a child package of `data_foundation`:

```text
validation/
|-- models.py       issue/result/context and Validator/Clock protocols
|-- candidates.py   structural pre-Domain candidate contracts
|-- rules.py        pure structural and semantic rules
|-- validators.py   CanonicalRecord and DailyBar orchestration
|-- service.py      explicit supported-type dispatch
`-- __init__.py     public validation surface
```

Candidate protocols allow parsed external data to be checked before it can satisfy the
strict Phase 1 constructors. Official Domain models remain unchanged and keep their
construction invariants. A `ValidationContext` owns the injected Clock, one centralized
future-skew tolerance and supported schema versions.

Rules return immutable issues and never repair values. Validators collect every
detectable issue, then produce field/code-sorted immutable results. `valid` is derived
from the error tuple. The engine is synchronous and contains no network, database,
Provider Runtime, Infrastructure or Presentation dependency.

Phase 2 deliberately does not enforce `event_time <= observed_at <= ingested_at`.
Phase 1 defines the timestamps independently, and Provider observation semantics may
not justify a universal order without a source-specific contract. This avoids inventing
a rule. Trading-date calendar validation is also deferred; no holiday service or market
timezone registry is introduced.

Validation and Quality remain separate: Phase 2 decides legality; Phase 3 will assess
freshness, completeness, source confidence and conflicts for already legal data.
