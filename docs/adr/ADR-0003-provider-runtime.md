# ADR-0003: Provider Runtime boundary

## Status

Accepted for SPEC-003 V1.0 on 2026-07-29.

## Context

The Checkpoint 2 `DataProvider.fetch()` port proves source replacement but does
not own provider metadata, capabilities, lifecycle, health, selection,
attribution, metrics, or failover. Adding those concerns to Application use
cases or to a single provider interface would couple business orchestration to
runtime and vendor behavior.

## Decision

Add an in-process Provider Runtime between Application ports and concrete
providers. Use a small lifecycle `Provider` protocol composed with an explicit
`ProviderInvocationHandler`. Keep runtime models framework-independent and keep
the package flat until a component has multiple implementations or duties.

Application keeps the existing `DataProvider` contract. A later SPEC-003 phase
will connect it to Provider Runtime through an adapter. The existing Event Bus
accepts a controlled event protocol so data and provider-runtime events share
one delivery boundary. Time and ID creation are injectable.

## Consequences

- Application does not learn concrete provider names.
- Runtime selection and failure policy can be tested without external SDKs.
- Existing `/data/{record_id}` behavior can remain compatible.
- Runtime state is process-local in V1.0 and is lost on restart.
- Async lifecycle and concurrency behavior require focused tests before the
  runtime is connected to application startup.

## Risks and rollback

The main risks are interface growth, invalid state transitions, cancellation
leaks, and failover hiding permanent errors. Separate policy components,
immutable snapshots, structured errors, and architecture tests mitigate them.
Rollback is a revert of SPEC-003 commits; no database migration is involved.
