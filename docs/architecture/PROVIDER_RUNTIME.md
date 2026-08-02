# Provider Runtime

## Implemented boundary

SPEC-003 Phase 1 defines the framework-independent runtime vocabulary and
contracts. Phase 2 adds in-process registration and explicit provider
construction. Phase 3 adds validated lifecycle execution and health monitoring.
Phase 4 adds pure selection and quality scoring. The runtime does not invoke,
fail over, or expose providers through HTTP.

The package intentionally uses a flat Python structure:

```text
provider_runtime/
|-- models.py       immutable metadata, capability, health and audit values
|-- interfaces.py   lifecycle, invocation, runtime, metrics, clock and ID ports
|-- errors.py       stable error taxonomy
|-- registry.py     atomic registration and immutable snapshots
|-- factory.py      explicit implementation allowlist
|-- lifecycle.py    validated state transitions and lifecycle events
|-- health.py       bounded health checks, thresholds and background tasks
|-- scoring.py      pure explainable quality calculation
|-- selector.py     pure filtering and deterministic ordering
|-- system.py       UTC clock and UUID implementations
`-- __init__.py     public contract surface
```

The base `Provider` protocol owns identity, capabilities and lifecycle only.
Business calls use the separate `ProviderInvocationHandler`, preventing the
base protocol from accumulating vendor or domain-specific methods.

Provider Runtime remains independent of FastAPI, Pydantic, Bootstrap,
Infrastructure and concrete Providers. Domain does not depend on Provider
Runtime. Composition and the compatibility adapter for the existing
`DataProvider.fetch()` port are deferred to later approved phases.

## Phase 2 registration semantics

- `ProviderDefinition` validates identity, implementation name, capability
  declarations, priority, concurrency, queue timeout, and copies configuration.
- `ProviderFactory` accepts a copied map of approved builders. It never imports
  arbitrary modules and rejects providers that differ from their definition.
- `ProviderRegistry` performs atomic register and unregister operations under
  an async lock. It never calls Provider lifecycle or health methods.
- Registration captures immutable metadata and capabilities. Read operations
  return snapshots sorted by Provider ID and do not expose registry internals.
- An enabled Provider starts as `REGISTERED`; a disabled Provider starts as
  `DISABLED`.

## Phase 3 lifecycle ownership

- `ProviderRegistry` remains responsible for registration and queries. Its
  private atomic state-storage hook is called only by `ProviderLifecycleManager`;
  an architecture test enforces this boundary.
- `ProviderLifecycleManager` is the sole status owner. It serializes changes per
  Provider, validates every transition, calls initialize and shutdown, and
  publishes lifecycle events through the existing Event Bus.
- `ProviderHealthManager` performs time-bounded checks and maintains consecutive
  success/failure counters. It cannot write status directly and requests changes
  through `ProviderLifecycleManager`.
- Background health tasks are explicit, idempotent to start, and cancellable.

The allowed state transitions are:

```text
REGISTERED -> INITIALIZING | DISABLED
INITIALIZING -> READY | FAILED
READY -> DEGRADED | UNAVAILABLE | STOPPING | DISABLED
DEGRADED -> READY | UNAVAILABLE | STOPPING | DISABLED
UNAVAILABLE -> DEGRADED | READY | STOPPING | DISABLED
STOPPING -> STOPPED | FAILED
DISABLED -> INITIALIZING
FAILED -> INITIALIZING
STOPPED -> terminal
```

An unhealthy check degrades a ready Provider immediately. The configured
consecutive-failure threshold makes it unavailable. Recovery is deliberately
staged: the success threshold moves `UNAVAILABLE` to `DEGRADED`, and a second
success window moves `DEGRADED` to `READY`.

## Phase 4 selection boundary

The caller supplies immutable Registry and Metrics snapshots plus an explicit
UTC timestamp. `ProviderSelector` performs no I/O and holds no Registry,
Lifecycle, or Health Manager. `QualityScorer` is stateless and never obtains the
current time itself.

Filtering order is enabled, exact capability, explicit exclusion, lifecycle,
health, cooldown, then capacity. Sorting order is preferred rank, lifecycle
(`READY` before `DEGRADED`), score descending, priority descending, and Provider
ID ascending. Structured reason enums make both exclusion and ordering auditable.
