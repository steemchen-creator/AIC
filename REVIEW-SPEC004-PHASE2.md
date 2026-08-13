# SPEC-004 Phase 2 Review

Review date: 2026-08-13

Branch: `feature/real-data-foundation`

## 1. Executive Summary

SPEC-004 Phase 2 adds a deterministic, synchronous Validation Engine for canonical
record candidates and typed DailyBar values. It separates data legality from future
data-quality assessment, reports all detectable issues without modifying input, and
remains independent of Provider Runtime, network, database and presentation layers.

Local acceptance passes with 234 tests, 94.89% full configured coverage and 100%
Validation Engine coverage.

## 2. Git / PR Status

- Branch: `feature/real-data-foundation`.
- Base: `main`.
- Existing Draft PR: [#5](https://github.com/steemchen-creator/AIC/pull/5).
- PR remains Draft; merge is not authorized.
- Phase 2 commit and final CI status are recorded after publication.

## 3. Architecture Diff

```text
data_foundation/validation/
|-- models.py       immutable issues, results, context and protocols
|-- candidates.py   structural pre-Domain candidate contracts
|-- rules.py        pure validation rules
|-- validators.py   CanonicalRecord and DailyBar validators
|-- service.py      explicit supported-type dispatch
`-- __init__.py     public API
```

The package depends only on standard-library types and the inward market-data Domain.

## 4. Added / Modified Files

Added implementation: six files under `data_foundation/validation`. Added tests:
`test_validation_models.py`, `test_daily_bar_validator.py`,
`test_canonical_validator.py`, and `test_validation_service.py`.

Modified: Data Foundation exports, architecture tests, SPEC-004 specification,
architecture/testing documents and `CHANGELOG.md`. No Provider Runtime file changed.

## 5. Validation Architecture

Candidate Protocols permit structurally parsed data to be checked before it can meet
strict Phase 1 Domain constructors. Validators execute fixed pure rules, collect all
detectable issues, and return an immutable result. The Service explicitly dispatches
only `DailyBar` and `CanonicalRecord`; there is no reflection, plugin scan or dynamic
import.

## 6. ValidationIssue Model

`ValidationIssue` is frozen and slotted. It contains a stable uppercase code,
`ERROR`/`WARNING` severity, optional nonblank field and nonblank audit message. Engine
messages are fixed and contain neither raw payloads nor exception traces.

## 7. ValidationResult Model

Errors and warnings are immutable tuples sorted by `(field, code)`. The `valid`
property is derived as `not errors`, preventing callers from constructing a result
whose boolean contradicts its issues. Warning support exists, but no Phase 2 warning
rule is defined.

## 8. Structural Rules

Rules cover record ID/type, schema version, timezone-aware timestamps, future skew,
instrument identity, provenance, immutable safe payload vocabulary, DailyBar trading
date and numeric field types. Unsupported schema version is
`UNSUPPORTED_SCHEMA_VERSION`.

## 9. DailyBar Semantic Rules

- `high >= max(open, close, low)` — `DAILY_BAR_HIGH_INVALID`.
- `low <= min(open, close, high)` — `DAILY_BAR_LOW_INVALID`.
- Each OHLC price must be non-negative — `DAILY_BAR_PRICE_NEGATIVE`.
- Volume must be a non-negative integer — `DAILY_BAR_VOLUME_NEGATIVE` or type issue.
- Turnover must be non-negative Decimal — `DAILY_BAR_TURNOVER_NEGATIVE` or type issue.
- Zero remains legal; no subjective market rule was added.

## 10. Timestamp Rules

All candidate timestamps must be timezone-aware. Future time is evaluated against an
injected validation Clock and one `max_future_skew` context value; the Engine never
calls real system time. UTC and `+08:00` are accepted. The exact tolerance boundary is
accepted and values beyond it fail with `TIMESTAMP_FUTURE`.

No universal `event_time <= observed_at <= ingested_at` rule was added because Phase 1
does not establish a provider-independent ordering guarantee. No trading-calendar or
market-timezone service is invented.

## 11. Provenance Rules

Validation checks nonblank Provider ID and transformation version, lowercase SHA-256
raw hash, non-negative integer failover count, consistent failover attribution,
timezone-aware optional provider timestamp, nonblank optional URI, and credential-risk
URI user info/query keys. Multiple provenance issues are collected in one result.

## 12. Canonical Rules

Canonical validation checks record identity/type/schema, all three timestamps,
provenance, optional instrument identity and recursively safe immutable payload values.
It does not copy DailyBar financial rules into the envelope validator.

## 13. Determinism Evidence

Issue sorting is intrinsic to `ValidationResult`. Tests validate the same multi-error
candidate 100 times and compare complete results, error codes and ordering. All results
are identical. The Clock and supported schema versions are explicit immutable inputs.

## 14. No Auto-Correction Evidence

A test retains an invalid high and negative volume before and after validation and
proves the frozen DailyBar remains byte-for-value equal. The Engine does not abs,
round, fill, infer, repair or replace any input field. Decimal precision is unchanged.

## 15. Architecture Boundary Review

Automated AST/source tests prove Validation imports no Provider Runtime, Provider,
Infrastructure, Presentation, FastAPI, Pydantic, SQLAlchemy, Redis, asyncpg, HTTP
client or network module. They also reject filesystem writes, socket/urlopen calls,
Quality Engine/Score and persistence repository concepts. No vendor SDK exists.

## 16. Test Evidence

Command: `.venv\Scripts\python.exe -m pytest -q --cov --cov-report=term-missing -ra`

Result: **234 passed in 5.34s**. No skip, xfail or warning was reported. Tests include
every required OHLC case, all negative financial fields, simultaneous errors,
timestamp tolerance, provenance, safe payload, Service dispatch, 100-run determinism
and 10,000 validations without a flaky time threshold.

## 17. Coverage

- Full configured coverage: **94.89%** (threshold 90%).
- Validation Engine total: **100%** statement and branch coverage.
- `DailyBarValidator` module: **100%**.
- Phase 2 required core threshold: at least 95%; passed.

## 18. Ruff

Command: `.venv\Scripts\python.exe -m ruff check apps/backend/src apps/backend/tests tests`

Result: **Passed — All checks passed.**

## 19. Mypy

Command: `.venv\Scripts\python.exe -m mypy --strict apps/backend/src`

Result: **Passed — no issues in 57 source files.**

## 20. Architecture Tests

Command: `.venv\Scripts\python.exe -m pytest apps/backend/tests/architecture -q`

Result: **13 passed in 0.13s.**

## 21. WPF Build

Command: `dotnet build apps/desktop/AIC.Desktop.csproj --configuration Release --no-restore`

Result: **Passed — 0 warnings and 0 errors.**

## 22. GitHub Actions

Draft PR #5 CI run
[`31677549949`](https://github.com/steemchen-creator/AIC/actions/runs/31677549949):

- Governance baseline: **Passed** in 6s.
- Backend tests: **Passed** in 36s.
- Desktop build: **Passed** in 54s.

This run verified Phase 2 implementation commit `1bcfaae`. The evidence-only document
commit remains subject to the same required checks before final handoff.

## 23. Known Limitations

- Only CanonicalRecord and DailyBar dispatch are supported.
- Supported schema versions are caller-configured; Phase 2 uses `1.0` in composition
  and tests but does not add a global configuration system.
- No time-order rule is asserted across event/observed/ingested timestamps.
- No exchange trading-calendar or formal market-timezone registry exists.
- Warning rules are intentionally absent to avoid Quality overlap.
- Secret URI detection is defense-in-depth, not a complete credential classifier.

## 24. Technical Debt

| ID | Description | Severity | Disposition |
|---|---|---:|---|
| TD-004-05 | Service dispatch is explicit for two concrete Domain types | Low | Extend only with approved typed canonical models |
| TD-004-06 | Candidate Protocol malformed inputs require parser/adapters in later Phase | Low | Phase 4 normalization boundary |
| TD-004-07 | No provider-independent timestamp order contract | Low | Decide only with evidence from approved sources |
| TD-004-08 | URI secret-key denylist is finite | Medium | Enforce Provider adapter security contract before real API |

No item blocks the pure Phase 2 engine.

## 25. Scope Confirmation

Confirmed:

- Phase 3 has not started.
- Data Quality Engine is not implemented.
- Freshness Quality Score is not implemented.
- Conflict Resolution is not implemented.
- Normalization Pipeline is not implemented.
- Persistence is not implemented.
- No real Provider is connected.
- Database and migrations are unchanged.
- SPEC-003 Provider Runtime is unchanged.

## 26. Final Recommendation

**APPROVED FOR PHASE 2 ARCHITECTURE REVIEW**, conditional only on PR #5 GitHub
Actions passing. The Engine satisfies the required purity, determinism, structural and
DailyBar semantic rules, error aggregation, no-auto-correction, coverage and boundary
requirements. Stop and wait for Architecture Review; do not begin Phase 3.
