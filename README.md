# AIC

机构级A股智能金融终端

## Repository governance

This GitHub repository is the Single Source of Truth for AIC. Development takes place on dedicated `feature/*` branches and reaches `main` only through Pull Requests.

Detailed development and security rules are maintained in [AGENTS.md](AGENTS.md). Project changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## Data Foundation architecture

SPEC-004 Phase 10 adds source-neutral corporate-action and adjustment-factor facts plus
explicit RAW, forward-adjusted and backward-adjusted DailyBar views. Raw canonical bars,
volume and turnover are never overwritten. See `docs/data/CORPORATE_ACTIONS.md` and
`docs/data/ADJUSTED_DAILY_BARS.md`.

The backend follows inward Clean Architecture dependencies:

```text
presentation -> application -> domain
                    ^
                    |
        providers and infrastructure
```

Concrete adapters are selected only by `bootstrap`. TASK-002 uses a deterministic
Mock Provider and in-memory Repository, Cache, and Event Bus. It contains no real
data-source or stock functionality.

```text
apps/backend/
|-- src/aic_backend/
|   |-- presentation/    HTTP boundary
|   |-- application/     Use cases and outbound ports
|   |-- domain/          Framework-independent models and events
|   |-- data_foundation/ Deterministic real-data identity and construction helpers
|   |-- providers/       Data-source adapters
|   |-- infrastructure/  Repository, cache, event, and operational adapters
|   |-- bootstrap/       Dependency composition
|   `-- shared/          Outer-layer configuration and logging
`-- tests/               Domain through architecture verification
```

## Foundation prerequisites

- .NET 8 SDK
- Python 3.12+
- Docker Desktop with Docker Compose and WSL 2
- Git

## Start the Windows client

```powershell
dotnet run --project apps/desktop/AIC.Desktop.csproj
```

The Checkpoint 1 window is intentionally limited to the AIC product name and version.

## Start the backend locally

Create and activate a virtual environment, then install the backend and test dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
$env:AIC_ENVIRONMENT = "development"
uvicorn aic_backend.main:app --reload
```

The backend exposes:

- `GET /` -> `{"project":"AIC","status":"running"}`
- `GET /health` -> `{"status":"healthy"}`
- `GET /data/sample-1` -> deterministic Mock data record

Unknown data identifiers return HTTP 404. Run all backend tests with `pytest`.

## Start the Docker foundation

Copy `configs/environments/development.env.example` to a local `.env`, replace the placeholder password, then run:

```powershell
docker compose up --build -d
docker compose ps
```

This starts PostgreSQL, Redis, and the backend. The backend verifies both infrastructure connections before serving requests. Stop the environment with `docker compose down`; named data volumes are retained.

## Repository structure

```text
apps/       Desktop application and Clean Architecture backend
configs/    Environment configuration examples
docker/     Container build definitions
scripts/    Repository automation
docs/       Architecture and development documentation
.github/    CI and collaboration workflows
```

Detailed Data Foundation contracts are under [docs/architecture](docs/architecture/README.md),
[docs/api](docs/api/README.md), and [docs/testing](docs/testing/README.md).

SPEC-003 Provider Runtime V1.0 is merged and includes registration, lifecycle,
health, selection, scoring, invocation and bounded failover. SPEC-004 Phases 1–7 add
source-neutral canonical market-data models, provenance, deterministic identity and raw
hashing, Validation, Data Quality, and a fixture-only Raw-to-Canonical normalization and
ingestion pipeline plus idempotent PostgreSQL persistence and migration. Phase 6 adds
the first real Provider for Tushare Pro A-share daily bars. Set `AIC_TUSHARE_TOKEN`
only in the runtime environment and never commit its value.
Phase 7 adds database-only historical queries and explicit, resumable, idempotent
backfill with conservative coverage metadata. Configure inclusive request chunk size
with `AIC_HISTORICAL_CHUNK_DAYS` (default 365). See
[Historical DailyBars](docs/data/HISTORICAL_DAILY_BARS.md).

Phase 8 adds the authoritative SSE/SZSE trading-calendar foundation: persisted OPEN and
CLOSED facts, timezone-aware split sessions, explicit calendar sync and calendar-aware
DailyBar candidate gaps. See [Trading Calendar](docs/data/TRADING_CALENDAR.md).

Phase 9 adds Instrument Master and explicit daily trading status. Phase 10 adds Tushare
`adj_factor`/`dividend` adapters, resumable factor backfill and auditable corporate-action
sync. Adjusted requests fail when factor coverage is incomplete; ordinary historical reads
remain RAW by default and never trigger provider synchronization.
