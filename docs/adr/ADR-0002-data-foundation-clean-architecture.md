# ADR-0002: Data Foundation Clean Architecture

- Status: Accepted
- Date: 2026-07-28

## Context

Checkpoint 1 proved that the WPF client, FastAPI service, PostgreSQL, and Redis
could start together. Its backend package coupled presentation and operational
dependency startup closely enough that adding data sources there would make
business-facing code depend on technical choices.

TASK-002 requires framework-independent domain concepts and replaceable
provider, repository, cache, event bus, and database boundaries.

## Decision

Organize the backend under `apps/backend/src/aic_backend` with presentation,
application, domain, infrastructure, providers, bootstrap, and shared packages.
Application-owned protocols define all outbound dependencies. Infrastructure
and provider packages implement those protocols, and bootstrap alone chooses
their concrete implementations.

Use an immutable, source-neutral `DataRecord` as the smallest domain concept
needed to prove the architecture. Use deterministic in-memory implementations
and a mock provider for TASK-002.

## Consequences

- Domain and application behavior can be tested without FastAPI, Redis,
  PostgreSQL, Celery, or network access.
- A new provider can be added without changing the use case or presentation.
- Backend import and startup paths must be updated together.
- In-memory adapters do not provide durability or cross-process consistency;
  production adapters require later reviewed tasks.

## Risks and controls

- Layering can become ceremony without behavior. Contracts remain limited to
  the four required boundaries and one use case.
- Generic payloads defer schema-specific validation. A later domain task must
  introduce typed concepts before real data is accepted.
- Import-path regressions are controlled by architecture and startup tests.
