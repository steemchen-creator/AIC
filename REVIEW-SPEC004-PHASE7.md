# REVIEW — SPEC-004 Phase 7

## 1. Executive Summary

Historical A-share DailyBar query/backfill is implemented on the existing canonical
data and Provider Runtime path. Local acceptance passes. PR #5 remains Draft and must
not be merged before architecture review.

## 2. Git / PR Status

- Branch: `feature/real-data-foundation`
- Base: `main`
- Pull Request: #5, Draft
- Final commit/remote/PR-head equality: recorded externally after the final push.

## 3. Architecture Diff

Application now owns canonical historical reads and backfill metadata ports plus query
and backfill orchestration. Infrastructure adds PostgreSQL adapters and an operational
ledger. Tushare performs vendor translation only at its adapter boundary. Domain and
existing Runtime selection/failover contracts are unchanged.

## 4. Added / Modified Files

Added: historical ports/use cases, historical PostgreSQL adapter, migration 0003,
Application and PostgreSQL tests, historical operations documentation, and this report.
Modified: persistence read contract/adapters, ingestion summary conflict accounting,
Tushare request translation, configuration/examples, exports, quality coverage source,
architecture tests, README, CHANGELOG and affected architecture/provider/database/test
documentation. Exact paths are available in the PR file list.

## 5. Historical Query Port

`CanonicalDailyBarRepository.get_daily_bars()` accepts a market-qualified instrument
and inclusive dates. `HistoricalDailyBarService` returns immutable records, coverage
metadata and gaps without Provider or network access.

## 6. PostgreSQL Read Path

The adapter filters exact market/symbol/instrument type and inclusive trading dates in
one query, ordered by trading date and record ID. Stored provenance and quality snapshot
are reconstructed without mutation.

## 7. Coverage Model

`EMPTY`, `PARTIAL`, `COVERED` and reserved `UNKNOWN` are explicit. Only completed
Provider-request intervals prove coverage; stored rows alone do not.

## 8. Coverage Metadata Persistence

`daily_bar_backfill_attempts` is append-only operational evidence with Provider,
capability, instrument/range, UTC timing, status, counts and sanitized error code.

## 9. Gap Detection Semantics

Intervals are inclusive, clipped to the request, merged when overlapping/adjacent, then
subtracted deterministically. Weekdays, holidays, suspensions and absent rows are never
invented.

## 10. Backfill Use Case

`BackfillDailyBars` reads coverage, computes missing ranges, chunks them and invokes the
existing ingestion use case. Query and ensure/backfill remain separate operations.

## 11. Provider Runtime Path

Backfill uses Provider Runtime selection/failover, then Tushare, Raw Observation,
Normalization, Validation, Quality and canonical persistence. No parallel data path or
direct HTTP call exists in Application.

## 12. Chunking

Inclusive chunks are deterministic and configurable through
`AIC_HISTORICAL_CHUNK_DAYS` (default 365). V1 executes sequentially, which is bounded.

## 13. Partial Failure

Processing stops at the first partial/failed chunk. Successful earlier chunks remain
committed and recorded; the failed interval is structured in the result.

## 14. Resume / Idempotency

Later execution skips completed coverage and resumes unconfirmed gaps. Canonical primary
key uniqueness makes repeated and concurrent execution duplicate-safe.

## 15. Canonical Units

Tushare lots become shares by ×100 and thousand CNY becomes yuan by ×1000. Decimal
financial values remain exact.

## 16. Event Time

Daily event time remains 15:00 Asia/Shanghai / 07:00 UTC, a period-end semantic rather
than a claimed last-trade timestamp.

## 17. Validation / Quality

Existing Phase 2 Validation and Phase 3 Quality execute unchanged for every row. The
first persisted quality snapshot remains immutable.

## 18. Provenance

Provider ID, source record/URI/time, raw hash, transformation version and failover
attribution survive the full PostgreSQL round trip.

## 19. Identity Conflict

Conflicts are counted as row failures and make a chunk partial. They are not converted
to success and never trigger overwrite.

## 20. No Silent Overwrite

Insert-or-verify remains authoritative. `force_refresh` repeats acquisition but cannot
replace a different financial fact or the first quality snapshot.

## 21. Error Mapping

Provider auth/rate-limit/malformed/runtime errors, invalid requests, identity conflicts
and persistence availability failures remain structured. Database driver and Windows
connection errors are converted to safe persistence codes with chained causes.

## 22. Observability

Backfill logs structured IDs, instrument, range, status and counts. Credentials, raw
payloads and private financial content are excluded.

## 23. PostgreSQL Evidence

PostgreSQL 17 integration verifies exact ordered reads, two unique facts under repeated
and concurrent backfills, attempt counts, safe unavailable errors and no SQLite proxy.

## 24. Migration Evidence

`20260817_0003` upgrades from Phase 6, creates the ledger/index/constraints, downgrades
to `20260814_0002`, and upgrades to head successfully in integration tests.

## 25. E2E Evidence

The test assembles the actual Registry/Lifecycle/Health/Selector/Invocation/Failover
Runtime, sanitized Tushare HTTP fixture, ingestion pipeline and PostgreSQL adapters.
Reverse Provider rows are returned in canonical ascending order; the repeated query
causes zero additional Provider calls.

## 26. Architecture Tests

Automated rules verify Application has no concrete Provider/Infrastructure/HTTP/SQL
dependency, the backfill reuses Runtime and ingestion, Tushare has no persistence
dependency, and unrelated business modules are absent.

## 27. Test Evidence

Local full suite: `pytest -q` — **372 passed**. Phase 7 scoped suite — **31 passed**.
Docker Compose image build and config passed; isolated backend, PostgreSQL 17 and Redis
containers were all healthy and `/health` returned `{"status":"healthy"}`. Temporary
verification volumes were removed; pre-existing local volumes were not modified.

## 28. Coverage

`pytest --cov --cov-report=term-missing -q` — **372 passed**, total **96.51%**
(rounded table total 97%); historical port/service/metadata/canonical adapter are 100%,
backfill is 98%, ingestion is 99%, Tushare Provider is 97%. Required 90% gate passed.

## 29. Ruff

`ruff check .` — passed.

## 30. Mypy

`mypy --strict apps/backend/src` — passed, 76 source files.

## 31. WPF Build

Release build passed with 0 warnings and 0 errors.

## 32. GitHub Actions

Pending final pushed HEAD at documentation time. Exact immutable result is supplied in
the PR timeline/final external attestation after GitHub Actions completes, avoiding an
evidence-only commit loop.

## 33. Final HEAD Attestation

The final external attestation will state Local HEAD = Remote branch HEAD = PR #5 HEAD,
the exact SHA, CI run/check conclusions and clean workspace after final push.

## 34. Known Limitations

No trading-calendar engine; closed sessions and suspensions are not inferred. No
corporate-action adjustment engine; current bars retain unadjusted/raw Provider
semantics. No scheduler or distributed worker is introduced.

## 35. Technical Debt

Future reviewed work may add an authoritative exchange calendar, adjustment contracts,
distributed job leasing and richer operational metrics. None is required or implied by
this V1 implementation.

## 36. Scope Confirmation

Historical A-share DailyBar query/backfill implemented.

No real-time data. No minute/Tick/Level-2. No financial statements. No
news/announcements. No institutional/social-security/national-team module. No second
real Provider. No cross-provider reconciliation. No trading calendar engine beyond
Phase 7 conservative semantics. No corporate-action adjustment engine. No strategy.
No AI investment decision. No portfolio. No paper trading. No live trading. No UI.
PR #5 remains Draft.

## 37. Final Recommendation

Recommend architecture review of Draft PR #5 after final CI attestation. Do not merge
and do not begin Phase 8 until explicitly approved.
