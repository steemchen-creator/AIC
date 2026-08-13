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
