# Data Foundation Testing

## Strategy

TASK-002 tests are deterministic and require no network, database, Redis, or
broker. Test layers mirror the backend architecture:

- Domain tests validate model and event identity, time, and immutability invariants.
- Provider contract tests validate deterministic Mock behavior and fixtures.
- Infrastructure tests validate repository, cache, and event adapters alone.
- Application tests validate cache -> repository -> provider ordering and side effects.
- Presentation tests validate HTTP contracts and Checkpoint 1 compatibility.
- Architecture tests parse imports and enforce inward dependency rules.
- Presentation tests verify that `/health` remains a liveness response without
  invoking a runtime dependency probe.

Architecture tests cover Domain -> Application, Providers -> Presentation,
Infrastructure -> Presentation, Presentation -> Bootstrap, Application ->
concrete adapter prohibitions, and the Bootstrap-only composition rule.

## Commands

```powershell
python -m pip install ".[test]"
python -m pytest -q
dotnet build apps/desktop/AIC.Desktop.csproj --configuration Release
docker compose config --quiet
docker compose up --build -d
```

Container acceptance additionally checks `/health`, `/data/sample-1`, and a 404
from `/data/missing`.

## Exclusions

No real provider, performance, load, schema migration, persistence, market,
financial, news, AI, strategy, or portfolio test belongs to TASK-002.

## SPEC-004 Phase 1 verification

Phase 1 tests cover:

- market-qualified instrument identity and instrument-type distinction;
- timezone acceptance, naive-time rejection and deterministic UTC conversion;
- preservation of event, observed, ingested and market trading-date semantics;
- deterministic record IDs across equivalent time zones and repeated calls;
- identity changes for market, instrument, event time, record type and discriminator;
- canonical SHA-256 raw hashing independent of mapping key order;
- immutable nested payload and source metadata values;
- complete provenance attribution and rejection of credential-bearing URIs;
- exact `Decimal` price/turnover behavior and integer volume;
- typed `DailyBar` construction without Phase 2 OHLC validation;
- architecture isolation from Runtime, FastAPI, Infrastructure, network, database,
  Validation, Quality and Persistence implementations.

Phase 1 core coverage is measured separately and must remain at least 95%:

```powershell
.venv\Scripts\python.exe -m pytest apps/backend/tests/data_foundation `
  --cov=aic_backend.data_foundation `
  --cov=aic_backend.domain.market_data `
  --cov-report=term-missing
```

The full repository gate also runs pytest with configured branch coverage, Ruff,
Mypy strict, architecture tests, the WPF Release build, `git diff --check`, and CI.
There are no network, database or real-Provider tests in Phase 1.

## SPEC-004 Phase 2 verification

Validation tests cover immutable issues/results, severity classification, derived
validity, deterministic ordering, schema support, required fields, timezone offsets,
naive and future timestamps with an injected Clock, instrument identity, provenance,
credential-bearing URIs and immutable safe payload vocabulary.

DailyBar tests cover every required OHLC relation, negative prices, volume and turnover,
field type failures, multiple simultaneous errors, stable issue order, unchanged input,
unchanged Decimal precision, 100 identical repeated results and 10,000 synchronous
validations without a flaky wall-clock threshold.

The Validation Engine core and `DailyBarValidator` must each remain at least 95%
covered. Architecture tests reject Runtime, Provider, Infrastructure, Presentation,
FastAPI, HTTP client, database, filesystem write, dynamic network and Phase 3/Persistence
coupling. There are no Warning rules in Phase 2.

```powershell
.venv\Scripts\python.exe -m pytest apps/backend/tests/data_foundation `
  --cov=aic_backend.data_foundation.validation `
  --cov-report=term-missing
```

## SPEC-004 Phase 3 verification

Quality tests cover score clamp/rounding, immutable sorted unique flags, every source
classification and unknown fallback, DailyBar fresh/middle/stale thresholds, future
and naive reference inputs, optional/unavailable completeness, INCOMPLETE distinction,
fallback and unknown-source annotations, exact Decimal conflict detection, affected-
field consistency and absence of winner/average behavior.

Assessor tests require successful Validation, compare reassessment at different
reference times without record-ID change, prove no mutation of record/provenance/context
or conflicts, repeat a full assessment 100 times, and run 10,000 pure assessments
without a flaky wall-clock SLA.

Architecture tests prohibit Provider Runtime QualityScorer/Selector, concrete Provider,
Infrastructure, Presentation, FastAPI, HTTP, database, filesystem writes, real SDK,
Persistence and Phase 4 Pipeline coupling. Data Quality core and DailyBar assessor must
each remain at least 95% covered.

```powershell
.venv\Scripts\python.exe -m pytest apps/backend/tests/data_foundation `
  --cov=aic_backend.data_foundation.quality `
  --cov-report=term-missing
```

## SPEC-004 Phase 4 verification

Pipeline tests cover the fixture DailyBar end-to-end path, stable structured parsing
errors, unsupported records, validation short-circuiting, quality-input failure,
failover provenance/flag propagation, explicit conflict context and reference-time
reassessment without record identity changes.

Determinism tests repeat the pipeline 100 times, reorder raw mapping keys, and prove no
mutation of raw payloads or quality context. Boundary cases cover missing/invalid
numbers, dates, timezone awareness, source metadata types, invalid OHLC, negative
volume, no auto-correction and propagation of unexpected programming errors.

Architecture tests prohibit network/database/filesystem writes, real Provider SDKs,
Presentation, Infrastructure and Provider Runtime internals. They also verify use of
the existing Validation and Quality engines, absence of copied formulas/OHLC rules, and
that fixture raw field names do not leak into Domain model fields. Normalization and
ingestion core modules must each remain at least 95% covered.

```powershell
.venv\Scripts\python.exe -m pytest `
  apps/backend/tests/data_foundation/test_ingestion_pipeline.py `
  --cov=aic_backend.data_foundation.normalization `
  --cov=aic_backend.data_foundation.ingestion `
  --cov-report=term-missing
```

Phase 4 has no database, migration, network, persistence, retry, reconciliation or real
Provider acceptance test because those capabilities are explicitly outside scope.

## SPEC-004 Phase 5 verification

Shared repository semantics cover first insert, identical duplicate, immutable first
quality snapshot, read-back and identity conflict. PostgreSQL tests additionally cover
concurrent duplicate writers, exact Decimal/date/time/instrument/provenance/flags round
trip, numeric-overflow rollback, safe unavailable errors, row count and repeatable
Alembic migration.

CI runs a PostgreSQL 17 service, executes `alembic upgrade head`, then the full pytest,
coverage, Ruff and Mypy gates. SQLite is not used as integration evidence. Application
tests prove normalization/validation failure outcomes cause zero repository writes.
