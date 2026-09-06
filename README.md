# AIC

机构级A股智能金融终端

## Repository governance

This GitHub repository is the Single Source of Truth for AIC. Development takes place on dedicated `feature/*` branches and reaches `main` only through Pull Requests.

Detailed development and security rules are maintained in [AGENTS.md](AGENTS.md). Project changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## Data Foundation architecture

SPEC-004 Phase 11 adds the Point-in-Time/As-Of access layer and explicit no-lookahead
controls. Historical Research and Operational Replay use different availability evidence;
unknown availability is never treated as available. See `docs/data/POINT_IN_TIME_DATA.md`
and `docs/data/NO_LOOKAHEAD_POLICY.md`.

## Deterministic backtest and portfolio foundation

SPEC-005 adds a provider-neutral portfolio accounting domain and a deterministic daily
replay application. Historical prices and trading days are available to the engine only
through `PointInTimeMarketDataService` with `HISTORICAL_RESEARCH`, an explicit aware
`as_of`, and RAW prices. Direct historical/latest repository reads are prohibited.

V1 supports multiple long-only positions, CNY cash, weighted-average cost, immutable
orders/fills, auditable cash and event ledgers, configurable fees, fixed-bps slippage,
daily NAV, a benchmark result, and normalized PostgreSQL evidence. It does not implement
partial fills, leverage, short selling, a strategy engine, live trading, AI or UI.
See `docs/backtest/BACKTEST_FOUNDATION.md` and `docs/portfolio/PORTFOLIO_ACCOUNTING.md`.

## A-share execution and pre-trade risk foundation

SPEC-006 adds a deterministic cash-account execution gate for A-share replay. Orders are
checked against PIT trading-calendar, instrument lifecycle/status and RAW DailyBars before
lot, price-limit, T+1 sellable-position, cash and configurable portfolio-risk rules.
Unknown required evidence is conservatively rejected; no latest-data fallback is allowed.

V1 enforces no short selling, no margin, no hidden leverage and non-negative cash. It records
stable RiskDecision, RiskSnapshot, settlement and audit evidence in PostgreSQL through an
Application-owned port. It does not implement strategy selection, Kelly sizing, dynamic
leverage, live trading, broker connectivity or UI. See
`docs/execution/A_SHARE_EXECUTION.md`, `docs/risk/PRE_TRADE_RISK.md` and
`docs/portfolio/T1_SETTLEMENT.md`.

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
|   |   `-- portfolio/   Deterministic accounting and cost policies
|   |   `-- execution/   A-share eligibility, T+1 and risk policies
|   |   `-- paper/       Forward paper account, session and performance models
|   |-- data_foundation/ Deterministic real-data identity and construction helpers
|   |-- providers/       Data-source adapters
|   |-- infrastructure/  Repository, cache, event, and operational adapters
|   |-- bootstrap/       Dependency composition
|   `-- shared/          Outer-layer configuration and logging
`-- tests/               Domain through architecture verification
```

## Forward Paper Trading 与 Champion Portfolio

SPEC-007 新增严格向前推进的模拟交易运行时和官方 `AIC Champion Paper Portfolio`。
账户以 500,000 CNY 启动并连续复利，不按日重置；所有交易日、标的、状态、公司行动、开盘成交价
与收盘盯市价都必须通过 PIT Service，以 `OPERATIONAL_REPLAY` 语义读取。Unknown 或缺失证据
不会回退到历史数据库“最新完整数据”。

V1 使用前一时点已形成的 Intent 在下一交易日开盘执行，复用 SPEC-006 A 股风险与 T+1 规则，
并生成连续 NAV、回撤、收益/风险、Benchmark、成本和完整持仓周期统计。崩溃恢复、重复 Session、
缺失盯市和公司行动均采用确定性或安全暂停处理。详见
`docs/paper/PAPER_TRADING_RUNTIME.md`、`docs/paper/CHAMPION_PORTFOLIO.md` 和
`docs/performance/PERFORMANCE_BASELINE.md`。

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

Phase 11 is the backtest-safe access boundary. Future research must provide an aware `as_of`
and an explicit availability mode. V1 PIT pricing supports RAW only; PIT front/back-adjusted
requests fail explicitly so future factors cannot leak into historical decisions.
