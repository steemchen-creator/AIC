# SPEC-004 Real Data Foundation

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
- Phase 7: end-to-end real-data verification and final review.

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
