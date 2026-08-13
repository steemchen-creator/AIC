# SPEC-003 Provider Runtime V1.0 Final Architecture Review

Review date: 2026-08-13

Review scope: SPEC-003 Phase 1 through Phase 6

Evidence source commit: `8e13a1b198127774e5774df5e36dee14c9282b9f`

Branch: `feature/provider-runtime`

Draft PR: [#4](https://github.com/steemchen-creator/AIC/pull/4)

## 1. Executive Summary

The Provider Runtime V1.0 implementation is **APPROVED WITH NON-BLOCKING DEBT**.
The review found no correctness, compatibility, dependency-direction, security, or
resource-lifecycle issue that blocks V1.0. The implementation establishes a typed,
deterministic, in-process runtime for provider registration, lifecycle, health,
selection, scoring, invocation, and bounded cross-provider failover.

This approval does not claim production-provider readiness. Real providers,
persistent metrics, retry, circuit breaking, distributed coordination, complete
observability, and provider SLA history remain explicitly out of scope. The review
made no runtime-code change and did not begin a new SPEC.

## 2. Git / PR Status

| Item | Evidence at review capture |
|---|---|
| Branch | `feature/provider-runtime` |
| Local HEAD | `8e13a1b198127774e5774df5e36dee14c9282b9f` |
| Remote branch HEAD | `8e13a1b198127774e5774df5e36dee14c9282b9f` |
| Base | `main` at `1e6d93d6bc60ea119e44a8f7e54b20f49c603cf5` |
| PR | `#4`, OPEN, Draft, base `main`, merge state `CLEAN` |
| Existing PR checks | Governance baseline, Backend tests, Desktop build: SUCCESS |
| Phase commits | `0417e2c`, `7dffd9e`, `2d5b553`, `86aa8ff`, `ba1732e`, `22cf807`, `8e13a1b` |
| Unpushed commit before this report | None |
| Tracked workspace before this report | Clean |
| Ignored artifacts | `.venv`, caches, coverage data, Python bytecode, WPF `bin/obj`, egg-info; none tracked |

## 3. Runtime V1.0 Capability Matrix

| Capability | Status | Module | Test evidence |
|---|---|---|---|
| Provider Definition | Implemented | `models.py` | `test_models.py` |
| Registry | Implemented | `registry.py` | `test_registry.py` |
| Factory / explicit builder allowlist | Implemented | `factory.py` | `test_factory.py` |
| Lifecycle | Implemented | `lifecycle.py` | `test_lifecycle.py` |
| Health | Implemented | `health.py` | `test_health.py` |
| Selection | Implemented | `selector.py` | `test_selector.py` |
| Quality Score | Implemented | `scoring.py` | `test_scoring.py` |
| Invocation | Implemented | `invocation.py` | `test_invocation.py` |
| Timeout | Implemented | `invocation.py`, `health.py` | `test_invocation.py`, `test_health.py` |
| Cancellation | Implemented as native `asyncio.CancelledError` propagation | `invocation.py`, `health.py` | `test_invocation.py`, `test_health.py` |
| Concurrency Control | Implemented | `invocation.py` | `test_invocation.py` |
| Failover | Implemented | `failover.py` | `test_failover.py` |
| Retry | Not Implemented | --- | Out of Scope |
| Circuit Breaker | Not Implemented | --- | Out of Scope |
| Real Provider | Not Implemented | --- | Future Spec |
| Persistent Metrics | Not Implemented | --- | Future Spec |
| Distributed Runtime | Not Implemented | --- | Future Spec |

## 4. Final Architecture Diagram

```text
Domain                    Application Ports (EventBus)
   ^                                ^
   |                                |
   +---------------- Provider Runtime abstractions ----------------+
                                    |
          Registry / Factory / Lifecycle / Health
                                    |
              Selection / Scoring (pure snapshots)
                                    |
                    Invocation (one provider)
                                    |
              Failover (selector + invoker ports)
                                    |
                  future concrete providers
```

The arrows represent dependencies toward owned abstractions. Runtime has no
dependency on Presentation, FastAPI, WPF, Bootstrap, Infrastructure, or a vendor SDK.

## 5. Dependency Direction Review

| Rule | Result | Evidence |
|---|---|---|
| Domain does not depend on Runtime | Pass | `test_domain_uses_standard_library_only` |
| Application does not depend on concrete providers | Pass | `test_application_does_not_depend_on_outer_layers` |
| Runtime avoids outer layers and frameworks | Pass | `test_provider_runtime_does_not_depend_on_outer_layers` |
| Registry does not own lifecycle | Pass | only `lifecycle.py` calls `_replace_runtime_state`; architecture test enforces it |
| Health requests lifecycle changes | Pass | `ProviderHealthManager` delegates to `ProviderLifecycleManager.record_health` |
| Selector performs no invocation or I/O | Pass | pure snapshot inputs; architecture tests |
| Invocation does not mutate lifecycle | Pass | no lifecycle import; architecture test |
| Failover reuses Selector and does not retry same provider | Pass | `ProviderSelector` injection and attempted-ID exclusions |
| Factory forbids arbitrary import | Pass | copied explicit `ProviderBuilder` allowlist |
| Circular runtime dependency | Not found | AST architecture suite plus import inspection |

Architecture test command: `.venv\Scripts\python.exe -m pytest apps/backend/tests/architecture -q`

Result: **11 passed in 0.09s**.

## 6. Lifecycle State Machine

```text
REGISTERED  -> INITIALIZING | DISABLED
INITIALIZING -> READY | FAILED
READY       -> DEGRADED | UNAVAILABLE | STOPPING | DISABLED
DEGRADED    -> READY | UNAVAILABLE | STOPPING | DISABLED
UNAVAILABLE -> DEGRADED | READY | STOPPING | DISABLED
STOPPING    -> STOPPED | FAILED
DISABLED    -> INITIALIZING
FAILED      -> INITIALIZING
STOPPED     -> terminal
```

`ProviderLifecycleManager` is the only state writer and serializes each provider with
an `asyncio.Lock`. Invalid transitions raise `InvalidStateTransitionError`.
Initialization failures and shutdown failures transition to `FAILED` and expose a
sanitized lifecycle message. Health recovery is staged from `UNAVAILABLE` to
`DEGRADED` and then `READY`; a disabled provider may be initialized again.

Code, architecture documentation, and transition tests agree. Initialization failure,
legal/illegal transitions, terminal behavior, recovery, and concurrent mutation are
tested. A direct shutdown-failure test is absent (TD-004); the implementation branch is
present but uncovered at `lifecycle.py:114-116`.

## 7. Selection Rules

Actual filter order in `ProviderSelector._exclusion_reason`:

1. Enabled.
2. Exact Capability.
3. Explicit exclusion.
4. Lifecycle eligibility, including the `allow_degraded` rule.
5. Health (`UNHEALTHY` and `UNKNOWN` excluded).
6. Cooldown.
7. Concurrency capacity.

Actual deterministic sort order:

1. Preferred Provider rank.
2. `READY` before `DEGRADED`.
3. Quality Score descending.
4. Priority descending.
5. Provider ID ascending.

Preferred status never bypasses filters. Explicit and failover-attempt exclusions are
applied before sorting. Selector has no state-writing path. The deterministic stress
test performs 1,000 selections across 100 snapshots.

## 8. Quality Score Formula

```text
total = clamp(
    availability * 0.35
  + success_rate * 0.30
  + latency * 0.20
  + freshness * 0.10
  + priority * 0.05,
  0, 100
)
```

Defaults and normalization verified from `scoring.py`:

- New provider (`total_calls == 0`): success-rate score `60`.
- Missing p95 with p50 present: use p50 and record `used_p50_latency=True`.
- Missing both latency values: latency score `60`.
- Unknown freshness: freshness score `50` and `freshness_unknown=True`.
- Priority: `clamp(priority / 1000 * 100)`.
- Component mappings and total are clamped to `[0, 100]`.
- `QualityScoreBreakdown` preserves component values and default-use flags.

## 9. Invocation Flow

```text
Request validation against live Registry snapshot
  -> provider lookup
  -> timeout context (covers semaphore wait and handler execution)
  -> per-provider semaphore acquire
  -> ProviderInvocationHandler.invoke
  -> response type validation
  -> standardized success result or structured exception
  -> context-manager semaphore release on every path
```

The timeout budget includes semaphore waiting. Native `asyncio.CancelledError` is
re-raised after context-manager cleanup. Known `ProviderInvocationError` values retain
their stable taxonomy; unexpected exceptions are chained internally and converted to
a sanitized `ProviderExecutionError`. Invalid responses are rejected. The result
preserves provider source, request, capability, timing, and response payload. Invocation
does not perform selection, retry, failover, lifecycle mutation, or persistence.

## 10. Failover Flow

```text
Initial Selector decision
  -> Invocation
  -> structured ProviderInvocationError
  -> FailoverPolicy allowlist
  -> exclude all attempted IDs
  -> existing Selector with same snapshots
  -> next distinct Provider
  -> Invocation
```

`max_failover_attempts` defaults to `1` and counts provider switches, not total calls.
Zero permits only the initial invocation. A provider ID cannot repeat. There is no
same-provider retry. Only timeout, execution, and unavailable errors permit switching.
Non-allowlisted failures become `FailoverNotAllowedError`; exhausted budget or no
remaining selectable provider becomes `FailoverExhaustedError`. Results record ordered
attempts, failure codes, final provider source, and failover count. Exhausted errors
retain `last_error` and attempted IDs.

## 11. Error Taxonomy

| Area | Exception(s) | Stable code(s) | Retryable | Public-message safety |
|---|---|---|---|---|
| Registry / Factory | `ProviderRegistrationError`, `DuplicateProviderError`, `ProviderNotFoundError`, `InvalidProviderDefinitionError` | `PROVIDER_REGISTRATION_ERROR`, `PROVIDER_DUPLICATE`, `PROVIDER_NOT_FOUND`, `PROVIDER_DEFINITION_INVALID` | No | Safe runtime-generated messages |
| Lifecycle / Health | `ProviderLifecycleError`, `InvalidStateTransitionError` | `PROVIDER_LIFECYCLE_ERROR`, `PROVIDER_STATE_TRANSITION_INVALID` | No | Safe runtime-generated messages; health exceptions are replaced |
| Selection | `ProviderSelectionError`, `NoProviderAvailableError`, `CapabilityUnavailableError`, `InvalidSelectionContextError` | `PROVIDER_SELECTION_ERROR`, `PROVIDER_NO_AVAILABLE`, `PROVIDER_CAPABILITY_UNAVAILABLE`, `PROVIDER_SELECTION_CONTEXT_INVALID` | only no-provider | IDs/reason enums only; no config/payload |
| Invocation | `ProviderInvocationError`, `ProviderExecutionError`, `ProviderUnavailableError`, `ProviderRateLimitedError`, `ProviderTransientError`, `ProviderPermanentError` | corresponding unique `PROVIDER_*` codes | unavailable/rate-limited/transient only | Unknown errors sanitized; adapter-authored structured messages Not Proven |
| Timeout | `ProviderTimeoutError` | `PROVIDER_TIMEOUT` | Yes | Sanitized runtime-generated message |
| Cancellation | `ProviderCancelledError` model; runtime propagates native `asyncio.CancelledError` | `PROVIDER_CANCELLED` when explicitly constructed | No | Native cancellation carries no provider detail here |
| Invalid response/request/auth/capability/permission | dedicated invocation subclasses | unique `PROVIDER_RESPONSE_INVALID`, `PROVIDER_REQUEST_INVALID`, `PROVIDER_AUTH_CONFIGURATION`, `PROVIDER_CAPABILITY_NOT_SUPPORTED`, `PROVIDER_PERMISSION_DENIED` | No | Runtime messages safe; future adapter messages require contract review |
| Aggregate | `AllProvidersFailedError` | `PROVIDER_ALL_FAILED` | Yes | Defined but not used by V1 failover |
| Failover | `FailoverError`, `FailoverExhaustedError`, `FailoverNotAllowedError` | `PROVIDER_FAILOVER_ERROR`, `PROVIDER_FAILOVER_EXHAUSTED`, `PROVIDER_FAILOVER_NOT_ALLOWED` | No | Fixed public text; `last_error` remains internal |

No duplicate `error_code` was found. Policy uses exception types, not string matching.
No bare provider exception is exposed by the invocation manager. The base exception
object chains the original cause for internal diagnostics without embedding it in the
public message.

## 12. Concurrency & Resource Safety

| Concern | Evidence | Classification |
|---|---|---|
| Registry mutation | async lock around register/unregister/state replacement | Pass |
| Lifecycle mutation | per-provider lock | Pass |
| Health tasks | idempotent start, explicit stop/shutdown, cancellation awaited | Pass |
| Invocation capacity | per-provider semaphore | Pass |
| Timeout/cancellation cleanup | nested async context managers | Pass |
| Failover invocations | sequential, bounded, distinct-provider attempts | Pass |
| Runtime shutdown orchestration | component methods exist; no top-level host orchestration yet | Accepted V1 Limitation |
| Cross-process capacity | absent | Accepted V1 Limitation |

## 13. Snapshot Consistency

Registry snapshots, provider snapshots, metric snapshots, selection decisions, and
attempt records are frozen/copy-protected value models. Selection consumes one caller-
supplied registry snapshot and one metrics mapping. Failover reuses those initial
snapshots while excluding attempted IDs; it does not refresh metrics or registry state
between switches. Invocation separately rechecks live registry status and capability.

These guarantees are **single-process snapshot consistency**, not distributed
consistency. There is no cross-process lock, consensus, distributed semaphore, or
snapshot version coordination.

## 14. Security Review

| Control | Result | Evidence |
|---|---|---|
| Factory allowlist | Proven | builders supplied explicitly; no importlib/dynamic module path |
| Configuration exposure in Result | Proven absent | invocation results carry request/response metadata, not provider definition config |
| Unknown exception cleanup | Proven | converted to fixed `ProviderExecutionError` text |
| Token/API key logging | Runtime contains no logging calls; end-to-end adapter behavior Not Proven | no real provider or adapter logging in scope |
| Payload `repr` exposure | Not Proven end-to-end | runtime does not format payload into its own errors; future logging/adapters not present |
| Selection metadata | Proven bounded | IDs, scores, reason enums; no config or payload |
| Failover `last_error` | Internal model only | no Runtime HTTP endpoint exposes it |
| API internal exception exposure | No new Runtime API exists | existing API compatibility tests pass |

The remaining “Not Proven” items are future provider/observability integration gates,
not defects in the current framework-only runtime.

## 15. Dependency Review

SPEC-003 adds test-quality dependencies only: `mypy`, `pytest-cov`, and `ruff` under
the optional `test` dependency group. It does not add a runtime package dependency.
There is no new Redis, Kafka, Celery, SQLAlchemy, market-data SDK, or other external
runtime infrastructure coupling in `provider_runtime`.

**No new external runtime infrastructure dependency.**

## 16. API Compatibility

No Runtime HTTP write or read endpoint was introduced. Existing `/health` remains a
liveness response and existing `/data/{record_id}` behavior remains under the prior
application/provider compatibility path. Full presentation and regression tests pass.
No Provider Runtime internal model is directly exposed by FastAPI. No breaking API
change was found.

## 17. Database Impact

No migration or schema change exists in the SPEC-003 diff. Invocation records, metrics,
selection decisions, and failover attempt history are not persisted. Runtime state is
in process. Database impact: **none**.

## 18. Test Evidence

All commands below were rerun against the final-review source HEAD on 2026-08-13.

| Gate | Command | Result |
|---|---|---|
| Full Python suite + coverage | `.venv\Scripts\python.exe -m pytest -q --cov --cov-report=term-missing -ra` | 151 passed in 4.60s; 0 skip, 0 xfail, no warnings reported |
| Runtime coverage | same | 92.60% (1026 statements; 218 branches) |
| Failover | same | 100% |
| Invocation | same | 96% |
| Lifecycle | same | 96% |
| Registry | same | 93% |
| Health | same | 81% |
| Selection / Scoring / Factory / Errors | same | 100% each |
| Ruff | `.venv\Scripts\python.exe -m ruff check apps/backend/src apps/backend/tests` | All checks passed |
| Mypy strict | `.venv\Scripts\python.exe -m mypy --strict apps/backend/src` | Success; no issues in 44 source files |
| Architecture | `.venv\Scripts\python.exe -m pytest apps/backend/tests/architecture -q` | 11 passed |
| WPF Release | `dotnet build apps\desktop\AIC.Desktop.csproj --configuration Release --no-restore` | Success; 0 warnings, 0 errors |
| Diff hygiene | `git diff --check` | Passed |
| GitHub Actions before report commit | CI run `31673350592` | Governance, Backend, Desktop: SUCCESS |

The repository threshold is 90%; measured Runtime coverage is 92.60%.

## 19. Regression Matrix

| Phase | Preserved scope | Current regression evidence |
|---|---|---|
| 1 | models, protocols, capability, clock/ID, error vocabulary | `test_models.py`, `test_interfaces.py`, architecture suite |
| 2 | registry, factory, definition, registration, snapshots | `test_registry.py`, `test_factory.py` |
| 3 | lifecycle, health, events, task cleanup | `test_lifecycle.py`, `test_health.py` |
| 4 | deterministic selection and scoring | `test_selector.py`, `test_scoring.py` |
| 5 | invocation, timeout, cancellation, semaphore cleanup | `test_invocation.py` |
| 6 | bounded failover, exclusions, attempt history | `test_failover.py` |

The Git diff retains all Phase 1-6 test files. The collection/full run reported no
skip or xfail, and no earlier test was observed deleted or weakened.

## 20. Documentation Consistency

| Document | Result |
|---|---|
| `docs/specifications/SPEC-003-Provider-Runtime.md` | Phase 1-6 scope and constraints represented |
| `docs/architecture/PROVIDER_RUNTIME.md` | module ownership, transitions, filters, invocation, and failover match code |
| `docs/testing/PROVIDER_RUNTIME.md` | Phase 3-6 evidence categories and quality commands represented |
| `CHANGELOG.md` | Phase 1-6 notable changes recorded |
| `README.md` | Runtime package and verification workflow discoverable |

No document claims retry, circuit breaking, a real provider, persistent metrics, or a
distributed runtime is implemented. Known limitations are consistent with the code.

## 21. Known Limitations

- Runtime state and synchronization are single-process only.
- There is no cross-process coordination or distributed concurrency control.
- Metrics are snapshots supplied in memory and are not persisted.
- Failover reuses the initial Registry/Metrics snapshots; only invocation rechecks live
  provider status/capability.
- There is no same-provider retry.
- There is no circuit breaker.
- There is no real provider integration.
- There is no complete metrics/tracing/alerting observability pipeline.
- There is no historical Provider SLA store.
- There is no distributed rate limiting.
- Runtime is not yet composed into a top-level host shutdown/startup orchestrator.

These limitations are intentional V1 scope boundaries, not V1 correctness defects.

## 22. Technical Debt Register

| TD-ID | Description | Severity | Why accepted | Recommended future spec |
|---|---|---:|---|---|
| TD-001 | Runtime state, locks, semaphores, and health counters are process-local | HIGH | V1 explicitly targets framework foundation; no real provider or multi-node deployment exists | Distributed Runtime / Coordination |
| TD-002 | Failover reuses the initial Registry/Metrics snapshots | MEDIUM | Deterministic per-request behavior; invocation still rechecks live availability | Snapshot Versioning and Refresh Policy |
| TD-003 | Health module branch coverage is 81% | MEDIUM | Critical success, timeout, threshold, recovery, cancellation, and task paths pass; total gate exceeds 90% | Runtime Reliability Test Expansion |
| TD-004 | Shutdown-failure branch lacks a direct test | MEDIUM | Code transitions to `FAILED` with sanitized error; success/terminal behavior is tested | Runtime Reliability Test Expansion |
| TD-005 | Structured errors raised by future trusted handlers may carry adapter-authored messages whose sanitization is Not Proven | MEDIUM | No real adapter or Runtime HTTP exposure exists; unknown exceptions are sanitized | Provider Adapter Security Contract |
| TD-006 | `ProviderCancelledError` is defined while manager cancellation intentionally propagates native `asyncio.CancelledError` | LOW | Native task cancellation preserves asyncio semantics and is tested | Error Taxonomy Cleanup |
| TD-007 | `system.py` has a broad name for clock/ID implementations | LOW | Naming does not affect behavior or dependency direction | Runtime Package Maintenance |
| TD-008 | Aggregate `AllProvidersFailedError` is defined but V1 failover uses explicit NotAllowed/Exhausted errors | LOW | Explicit failover outcomes are clearer and tested | Error Taxonomy Cleanup |
| TD-009 | No top-level runtime host composes startup and shutdown of all managers | MEDIUM | Composition and real-provider host integration are outside Phase 1-6 | Provider Host Integration |

TD-001 is HIGH because it limits deployment topology, but it does not block V1: the
approved product of SPEC-003 is an in-process runtime foundation, not a distributed
production provider service.

## 23. Blocking Issues

**None found.**

No unauthorized API break, database change, external runtime infrastructure coupling,
dynamic provider import, layer inversion, duplicate provider retry, resource leak, or
unstructured public exception escape was found in the reviewed V1 scope.

## 24. Non-blocking Recommendations

1. Add direct tests for shutdown failure and remaining Health Manager task/interval
   branches before real providers are integrated.
2. Define an adapter security contract that forbids secrets in structured error
   messages, logs, request payload diagnostics, and provider metadata.
3. Decide snapshot refresh/version semantics before metrics become asynchronous or
   distributed.
4. Add explicit host startup/shutdown composition with bounded shutdown once real
   provider integration is approved.
5. Rename `system.py` to `runtime.py` or `core.py` only in a focused maintenance change.
6. Reconcile unused cancellation/aggregate error types without changing native asyncio
   cancellation semantics.

## 25. Final Recommendation

### B. APPROVED WITH NON-BLOCKING DEBT

Provider Runtime V1.0 is suitable for architecture-review handoff and may proceed to
the Ready for Review / merge decision **only when the Architecture Reviewer chooses**.
The implementation is internally coherent, deterministic, test-backed, and maintains
the approved boundaries. The debt register must remain visible for future Provider
Adapter, Reliability, Observability, and Distributed Runtime specifications.

PR #4 must remain Draft after this evidence package is pushed. This review does not
authorize merge, real-provider integration, Market Data Engine work, or a new SPEC.
