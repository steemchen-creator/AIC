# ADR-0001: Foundation Architecture

- Status: Accepted
- Date: 2026-07-28
- Decision owners: AIC maintainers

## Context

AIC needs a runnable engineering baseline before business capabilities can be developed. The foundation must support a Windows desktop, service backend, durable storage, caching, background work, isolated configuration, and repeatable local execution without introducing domain logic.

## Decision

- Use .NET 8 and WPF for the Windows desktop shell.
- Use Python 3.12+ and FastAPI for the backend shell.
- Provide PostgreSQL, Redis, and Celery connection and initialization boundaries without schemas, caching behavior, or tasks.
- Use Docker Compose for the backend, PostgreSQL, and Redis development topology.
- Keep shared configuration, logging, and exceptions under `core`; reserve `shared` for future contract types.

## Impact

The repository becomes a multi-language workspace with Windows-specific desktop builds and containerized backend infrastructure. CI and contributor workflows must validate both ecosystems.

## Risks

- Toolchain and dependency versions may drift across .NET, Python, and containers.
- WPF builds require Windows runners.
- Container startup depends on Docker Desktop and healthy PostgreSQL and Redis services.
- Configuration mistakes could expose credentials if contributors ignore the documented environment-variable workflow.
- Shared folders could become ungoverned coupling points if abstractions are added prematurely.

## Controls

Pin the .NET SDK, constrain Python dependencies, use environment variables for secrets, keep health checks explicit, prohibit business objects in the foundation, and require ADR review for later boundary changes.
