# SPEC-004 Phase 6 Review

## Executive Summary

Phase 6 implements the first real Provider vertical slice for Tushare Pro A-share
daily bars while retaining Provider Runtime, Validation, Quality, and persistence
boundaries. Recommendation: review after final remote CI evidence is attached.

## Git / PR

- Branch: `feature/real-data-foundation`
- Draft PR: https://github.com/steemchen-creator/AIC/pull/5
- Merge: prohibited; PR remains Draft.

## Provider Decision

The adapter calls Tushare's official JSON HTTPS contract with `httpx`. This avoids the
full SDK/pandas dependency and keeps timeout, response parsing, error mapping, and
credential handling inside one owned Provider adapter.

## Architecture Diff / Files

- Provider: `providers/tushare.py`; explicit builder: `bootstrap/provider_builders.py`.
- Runtime facade: `provider_runtime/runtime.py`.
- Pure normalizer: `data_foundation/tushare_normalization.py`.
- Vendor-neutral batch use case: `application/use_cases/ingest_daily_bars.py`.
- Tests cover adapter, runtime, normalization, orchestration, architecture, and
  PostgreSQL read-back/idempotency.
- Migration `20260814_0002` expands `record_id` storage from 64 to 80 characters,
  preserving the existing 68-character deterministic identity contract.
- README, CHANGELOG, specification, architecture, testing, deployment, environment,
  and `docs/providers/TUSHARE.md` were updated.

## Runtime Integration

Bootstrap exposes only the controlled implementation `providers.tushare_daily`.
Application requests capability `market.daily.read`; it neither imports nor names
Tushare. `ProviderRuntime` supplies current registry state to the existing
Selector/Invocation/Failover composition.

## Client Boundary / Credential Safety

`AIC_TUSHARE_TOKEN` is environment-only. Missing token becomes a stable initialization
failure. Token values are excluded from returned rows, RawObservation, provenance,
source URI, exceptions, fixtures, and documentation. Calls use explicit timeouts.

## Capability / API Contract

Capability is `market.daily.read` V1, batch mode. Minimal calls support one symbol plus
date range or one trade date. No HTTP presentation API was added or changed.

## RawObservation

Every provider row first becomes a canonical RawObservation with provider ID,
DailyBar capability, injected observation ID/time, deterministic SHA-256 raw hash,
and failover count. No response/DataFrame bypasses this boundary.

## Normalizer / Instrument / Date / Time

`000001.SZ` maps to `CN.SZSE`; `600000.SH` maps to `CN.SSE`. `YYYYMMDD` remains the
trading date. Event time is the daily period end, 15:00 Asia/Shanghai (07:00 UTC),
not a claimed precise last trade.

## Decimal / Volume / Amount

Decimal parsing is string-based and rejects None, bool, invalid values, NaN and
infinity. Tushare `vol` (手) is multiplied exactly by 100 to canonical shares.
Tushare `amount` (千元) is multiplied exactly by 1000 to canonical CNY yuan.

## Provenance / Version

Provenance retains provider/source identity, safe logical URI, failover attribution,
raw hash, and transformation version `tushare-daily-bar/v1`. Canonical deterministic
record ID remains independent of the vendor source ID.

## Validation / Quality / Persistence

Every good row passes existing DailyBar Validation and unchanged Quality assessment
with conservative `PUBLIC_FINANCIAL_API` source classification. Only successful rows
reach the Application persistence port and PostgreSQL adapter.

## Batch / Partial Failure

Summary fields are requested, received, succeeded, failed, persisted, and
already_exists. Rows process independently; one malformed row does not discard valid
siblings. Empty results are successful empty batches, distinct from provider errors.

## Errors / Timeout / Rate Limit

Tests cover missing credential, authentication, permission, rate limit, timeout,
network unavailable, malformed response, empty response, and invalid request. No
automatic retry, busy loop, or new retry engine was introduced.

## Health / Lifecycle / Selector

The Provider uses existing Registry, Lifecycle Manager, Health Manager, and Selector.
Health is a lightweight initialized/configuration check and consumes no data quota.
Lifecycle reaches READY only after credential initialization succeeds.

## Secret Safety

Fixtures are sanitized and deterministic. Example environment files contain empty
placeholders only. No live token was used, logged, or committed.

## E2E / Live Smoke / Idempotency / PostgreSQL Evidence

The PostgreSQL integration proves fixture Provider result → Runtime contract →
RawObservation → normalizer → Validation → Quality → INSERT/read-back. A second
ingestion yields ALREADY_EXISTS and the database retains one canonical fact. Tests use
an isolated PostgreSQL 17 container. Live smoke was not executed because no explicit
test token was supplied; required CI does not skip or depend on live network access.

## Architecture Tests

Automated tests prove: HTTP dependency stays in the Provider adapter; normalizer has no
network/DB dependency; adapter has no repository dependency; Application has no
Tushare dependency; persistence and Runtime core remain vendor-neutral.

## Test / Coverage / Ruff / Mypy / WPF / CI

- Local Python: 343 tests passed (including PostgreSQL and repeatable migration).
- Total branch coverage: 96%; Phase 6 orchestration 95%, normalizer 95%, adapter 97%,
  runtime facade 100%.
- Ruff: passed. Mypy strict: passed. Architecture tests: passed.
- WPF Release: passed with 0 warnings and 0 errors.
- Docker Compose config: passed. PostgreSQL 17 integration: passed.
- GitHub Actions and exact final remote HEAD: pending publication of this report.

## Final HEAD

The exact Local/Remote/PR HEAD and required-check result will be added after the final
report commit is pushed and GitHub Actions completes. The final PR attestation is the
authoritative non-self-referential SHA evidence.

## Known Limitations / Technical Debt

- Only `.SZ` and `.SH` daily bars are supported.
- Health verifies configuration/initialization, not a quota-consuming live query.
- No scheduling, automatic retry, real backup Provider, or live-smoke CI secret exists.
- Provider Runtime continues using its current ID grammar, hence `tushare_pro` rather
  than the specification's non-binding `tushare-pro` suggestion.

## Scope Confirmation

Only Tushare A-share DailyBar was added. No real-time/minute/L2, financial, news,
announcement, fund/institutional/national-team/social-security analysis, second
Provider, reconciliation, strategy, AI, trading, Portfolio, or UI work was added.
PR #5 remains Draft and is not merged.

## Final Recommendation

Proceed to architecture review after final GitHub Actions and exact HEAD attestation.
Do not merge and do not start a later phase before approval.
