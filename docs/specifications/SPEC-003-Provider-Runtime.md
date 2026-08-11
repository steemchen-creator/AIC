# SPEC-003 Provider Runtime

## Implemented phases

- Phase 1: framework-independent contracts, models, errors, Clock and ID ports.
- Phase 2: concurrency-safe Registry and explicit allowlist Factory.
- Phase 3: serialized Lifecycle and bounded Health management.
- Phase 4: deterministic Provider selection and explainable quality scoring.
- Phase 5: bounded single-Provider invocation with timeout, cancellation and
  concurrency cleanup.

## Phase 4 selection contract

Phase 4 only determines eligible Provider order. It performs no invocation,
timeout execution, semaphore acquisition, retry, failover, metrics collection,
network access, or real Provider integration.

Filtering uses the first matching reason in this fixed order: enabled,
capability, explicit exclusion, lifecycle eligibility, health eligibility,
cooldown, and concurrency capacity. Preferred IDs only reorder candidates that
pass every filter; an explicit exclusion always wins.

Candidate order is deterministic: preferred group and rank, `READY` before
`DEGRADED`, quality score descending, metadata priority descending, then
Provider ID ascending.

Quality Score is a pure calculation from immutable Provider and Metrics
snapshots plus an explicitly supplied UTC timestamp:

```text
availability * 0.35 + success rate * 0.30 + latency * 0.20
  + freshness * 0.10 + priority * 0.05
```

New Providers use success-rate and latency defaults of 60. Unknown freshness
uses 50 and is marked in the score breakdown. P50 is used only as an explicitly
marked fallback when P95 is absent.

`SelectionDecision` contains the selected ID, complete ordered candidates,
scores, score breakdowns, structured selection reasons, structured first
exclusion reasons, and the injected UTC decision time. No-candidate outcomes
distinguish unsupported capability from temporarily unavailable candidates.

## Phase 5 invocation contract

`ProviderInvocationManager` executes exactly one selected Provider through the
owned `ProviderInvocationHandler` protocol. It queries Registry snapshots but
does not modify Registry, Lifecycle, Health, or Selection state.

The request contains request and Provider IDs, exact Capability, immutable
payload, timeout and UTC creation time. Successful responses are standardized
with immutable data, latency and UTC start/finish times. Known runtime errors
remain structured; unknown Provider exceptions are wrapped with sanitized
messages while retaining the original exception as the internal cause.

The call-level timeout covers both concurrency acquisition and execution.
`asyncio` cancellation propagates normally. Semaphore context management
releases capacity after success, Provider error, timeout, or cancellation.
Phase 5 performs no retry or failover.
