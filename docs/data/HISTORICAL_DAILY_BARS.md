# Historical A-share DailyBar Query and Backfill

## Contract

Phase 7 adds an Application-owned historical query and explicit backfill path for
canonical A-share `DailyBar` records. Query is database-only: it never calls a Provider,
never refreshes implicitly, and returns an inclusive `[start, end]` range sorted by
`trading_date`, then `record_id`.

Backfill is a separate use case. It computes missing inclusive intervals from completed
backfill metadata, chunks them by `AIC_HISTORICAL_CHUNK_DAYS` (default 365), and processes
chunks sequentially through the existing Provider Runtime, Tushare adapter,
Normalization, Validation, Quality and canonical PostgreSQL persistence path.

## Conservative coverage semantics

Coverage is evidence-based, not calendar-derived. A range is confirmed only when a
Provider request for that exact interval completed, including a valid empty response.
Stored rows alone do not prove that dates without rows were closed, suspended, or
holidays. Failed and partial attempts never confirm their interval.

- `EMPTY`: no canonical rows and no completed coverage evidence.
- `PARTIAL`: rows or some completed intervals exist, but gaps remain.
- `COVERED`: completed intervals cover the entire requested inclusive range.
- `UNKNOWN`: reserved for a caller that cannot establish coverage evidence.

This version has no trading-calendar engine. It does not synthesize weekdays, holidays,
suspensions or missing bars.

Phase 8 optionally enriches the response when authoritative Calendar coverage is
complete. `expected_missing_dates` contains OPEN exchange dates without a bar and is a
candidate gap only: an exchange OPEN day may still be an instrument suspension. CLOSED
dates and partial/unconfirmed calendar ranges are never reported as proven bar gaps.

## Failure, resume and idempotency

Each chunk writes an immutable operational attempt with provider, capability,
instrument, range, UTC timestamps, status, counts and a sanitized error code. Processing
stops at the first partial or failed chunk. A later run skips only completed ranges and
resumes from the remaining gap. Canonical `record_id` uniqueness makes repeated and
concurrent requests idempotent; a different financial fact under the same ID is an
identity conflict and is never overwritten.

`force_refresh` requests the full range again but still uses insert-or-verify semantics.
It does not replace canonical facts or their first ingestion-time quality snapshot.

## Units, time and provenance

Canonical prices and turnover remain exact decimals. Tushare `vol` lots are converted
to shares (`×100`) and `amount` thousand CNY to yuan (`×1000`). Daily event time remains
15:00 Asia/Shanghai (07:00 UTC), representing period end. Every record retains Provider,
raw hash, transformation version, source record/URI/time and failover attribution.

## Known limitations

- No exchange trading calendar; coverage relies on completed Provider intervals.
- No corporate-action adjustment engine. Bars retain current unadjusted/raw Provider
  semantics and are not labeled as adjusted.
- No scheduler, distributed backfill queue, unbounded concurrency, second Provider,
  reconciliation, real-time/minute/Tick/L2 data, business strategy, AI or UI.
# Phase 9 gap classification

When Calendar, lifecycle and Trading Status evidence are available, missing bars are
classified as market closed, not listed, delisted, suspended, probable data gap, or
unknown. Insufficient evidence always produces `UNKNOWN`; probable gaps are not signals.
