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
