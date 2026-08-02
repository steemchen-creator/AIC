# SPEC-003 Provider Runtime

## Implemented phases

- Phase 1: framework-independent contracts, models, errors, Clock and ID ports.
- Phase 2: concurrency-safe Registry and explicit allowlist Factory.
- Phase 3: serialized Lifecycle and bounded Health management.
- Phase 4: deterministic Provider selection and explainable quality scoring.

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
