# SPEC-004 Real Data Foundation

Phase 6 completes the first real-data vertical slice for Tushare Pro A-share daily
bars. It reuses the SPEC-003 Runtime and Phase 1–5 pipeline; it introduces no
real-time, financial, news, strategy, AI, trading, or second-Provider capability.

## Goal

SPEC-004 defines how a Provider Runtime result can eventually become a trusted,
traceable financial-data fact. The complete V1 roadmap covers canonical models,
provenance, timestamp semantics, validation, quality assessment, normalization,
ingestion, persistence, and a separately approved first real Provider.

```text
Provider Runtime result
  -> Raw Observation
  -> Normalization
  -> Validation
  -> Quality Assessment
  -> Canonical Record
  -> Repository / Consumer
```

Business modules must not treat raw Provider output as trusted financial facts.

## Phase plan

- Phase 1: canonical models, typed `DailyBar`, instrument identity, timestamps,
  provenance, Raw Observation, deterministic identity and raw hashing.
- Phase 2: structural and semantic validation.
- Phase 3: data quality, freshness, completeness, source-confidence input and
  conflict representation.
- Phase 4: deterministic normalization and ingestion with fixtures.
- Phase 5: reviewed persistence, migrations and idempotent queries.
- Phase 6: reviewer-selected and separately specified real Provider.
- Phase 7: historical A-share DailyBar query, conservative coverage metadata,
  resumable backfill and PostgreSQL end-to-end verification.

## Phase 7 implementation: Historical query and backfill

The historical read port is owned by Application and reads canonical PostgreSQL facts
only. An explicit backfill use case determines gaps from completed Provider-request
intervals, splits inclusive ranges into bounded sequential chunks and reuses the
existing Runtime-to-persistence vertical slice. Partial or failed chunks remain audit
evidence but do not establish coverage; later requests resume from unconfirmed gaps.

Coverage deliberately does not infer exchange sessions from weekdays or existing rows.
This phase adds no trading-calendar or corporate-action adjustment engine. Full semantics
and limitations are documented in `docs/data/HISTORICAL_DAILY_BARS.md`.

## Phase 1 implementation

Phase 1 adds a pure domain vocabulary under `domain/market_data` and deterministic
construction helpers under `data_foundation`. It retains the existing TASK-002
`DataRecord` compatibility model and does not modify Provider Runtime.

The model distinguishes `event_time`, `observed_at` and `ingested_at`; all are
timezone-aware and normalized to UTC. `trading_date` remains a separate market-date
value and is never derived from a UTC rollover. Exact prices and turnover use
`Decimal`, and volume uses `int`.

The canonical key combines market and symbol, for example `CN.SSE.600519`; instrument
type remains an additional identity dimension. Record IDs use SHA-256 over canonical
identity components. Raw hashes use SHA-256 over type-delimited bytes or canonical
mapping serialization, so mapping key order cannot change the digest.

All mappings are defensively copied and recursively frozen. Canonical payload values
are limited to explicit scalar, date/time, sequence and string-keyed mapping types;
opaque arbitrary objects are rejected. Provenance contains no credential field and
rejects URI user information and common secret-bearing query keys.

## Phase 1 boundary

Phase 2 through Phase 7 have not started. Phase 1 contains no Validation Engine,
Quality Engine, Repository port or adapter, migration, database access, network call,
real Provider, retry, circuit breaker, UI, strategy, recommendation or AI behavior.

`DataCapability` is a source-neutral data-domain enum. A later approved adapter may
map it to a Provider Runtime capability without making Domain depend on Runtime.

## Phase 2 implementation: Validation Engine

Phase 2 adds synchronous, pure validation for `CanonicalRecord` and `DailyBar`
candidates. Validation answers whether a candidate is structurally and semantically
legal; it does not score the quality of a legal record.

`ValidationIssue` carries a stable uppercase code, `ERROR` or `WARNING` severity,
optional field and fixed audit message. `ValidationResult.valid` is derived from the
absence of errors, so contradictory states cannot be constructed. Issues are sorted by
field and code for deterministic output. Phase 2 defines Warning support but no Warning
rules, avoiding premature overlap with Phase 3 Quality flags.

Structural rules cover required identifiers, supported schema version, timezone-aware
timestamps, injected-clock future skew, instrument identity, provenance, immutable safe
payload vocabulary and DailyBar field types. Semantic DailyBar rules enforce OHLC
bounds, non-negative prices, volume and turnover. Zero values remain allowed.

Validation only reports issues. It never changes, rounds, fills, repairs or infers a
candidate field. It performs no I/O and does not catch programming errors as data
issues. The current service dispatches the two supported Domain record types explicitly;
there is no plugin scan, reflection or dynamic import.

Phase 3 through Phase 7 remain unstarted. No Data Quality Engine, freshness score,
conflict resolution, normalization pipeline, persistence or real Provider exists.

## Phase 3 implementation: Data Quality Engine

Phase 3 assesses already validated DailyBar data. The caller must supply a successful
Phase 2 `ValidationResult`; invalid data is explicitly rejected, and Quality does not
copy or redefine Validation rules.

The fixed V1 formula is freshness 30%, completeness 25%, consistency 25% and source
confidence 20%. Scores are clamped to 0–100 and rounded to two decimal places.
DailyBar freshness is 100 through one day, declines linearly until seven days, and is
0 plus `STALE` at seven days or later. Reference time is explicit; future events fail.

Completeness supports configured optional and source-unavailable fields. A partial gap
produces `MISSING_OPTIONAL_FIELD`; a score at or below the incomplete threshold produces
`INCOMPLETE`. Current typed DailyBar turnover is required, so normal completeness is 100.

Consistency uses exact Decimal conflict values and deducts by affected comparable-field
ratio. Conflicts are immutable observations; no winner, average or reconciliation is
produced. Source confidence uses the configurable V1 mapping
OFFICIAL_EXCHANGE/LICENSED_VENDOR/PUBLIC_FINANCIAL_API/DERIVED_SOURCE/UNKNOWN =
100/90/70/50/30. These are AIC policy inputs, not objective vendor claims.

`SOURCE_FALLBACK` and `UNKNOWN_SOURCE_TIMESTAMP` are annotations and do not cause a
second deduction. Quality is associated separately from Canonical Record identity, so
reassessment at another reference time never changes `record_id`.

Phase 4 is implemented as described below. Phase 5 through Phase 7 remain unstarted;
no persistence, reconciliation or real Provider exists.

## Phase 4 implementation: Normalization and Ingestion Pipeline

Phase 4 introduces a source-specific normalization boundary and a deterministic
orchestrator:

```text
RawObservation -> FixtureDailyBarNormalizer -> DailyBar
  -> Phase 2 Validation -> Phase 3 Quality -> IngestionSuccess | IngestionFailure
```

`DataNormalizer[T]` is the narrow normalization contract. The only implementation is
the explicitly named fixture normalizer, registered through an explicit mapping rather
than discovery or dynamic imports. It parses fixture fields, preserves the source
market `trading_date`, requires timezone-aware event/provider timestamps, uses exact
Decimal conversion, reuses `InstrumentIdentity`, and never repairs financial values.

The resulting provenance retains the Raw Observation provider, canonical payload hash,
source metadata and failover attribution. Its stable `transformation_version` is the
actual normalizer version. The deterministic financial `record_id` remains independent
of the execution-level `ingestion_id` and quality reference time.

`DataIngestionPipeline` only sequences Normalize, Validate and Assess. Validation
failure stops before Quality. Expected source-data errors become immutable structured
failures; unexpected programming errors propagate. Quality policy and OHLC rules remain
owned exclusively by the Phase 3 and Phase 2 engines.

Phase 5 persistence is implemented below. There is still no network I/O, real Provider,
retry, reconciliation or strategy logic, and SPEC-003 Provider Runtime remains unchanged.

## Phase 5 implementation: Persistence and Idempotent Storage

Phase 5 adds an Application-owned async canonical DailyBar repository port and two
contract-compatible adapters: an in-memory fake for Application tests and a PostgreSQL
Infrastructure adapter for production/integration evidence. A separate Application use
case accepts only Phase 4 outcomes; failed ingestion returns without writing, while a
successful outcome is persisted without normalization or validation repetition.

The PostgreSQL `canonical_daily_bars` table atomically stores the immutable financial
fact, provenance and ingestion-time quality snapshot. `record_id` is the primary-key
idempotency boundary. `INSERT ... ON CONFLICT DO NOTHING` followed by exact fact
comparison returns `INSERTED` or `ALREADY_EXISTS`; a different fact under the same ID
raises `PERSISTENCE_IDENTITY_CONFLICT`. No update or last-write-wins path exists.

Prices use `NUMERIC(28,10)`, turnover uses `NUMERIC(38,10)`, and scores use
`NUMERIC(5,2)`. Alembic owns the reversible schema migration. Phase 6 and real Provider
selection have not started; Redis is not canonical storage.
