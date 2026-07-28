# AIC

机构级A股智能金融终端

## Repository governance

This GitHub repository is the Single Source of Truth for AIC. Development takes place on dedicated `feature/*` branches and reaches `main` only through Pull Requests.

Detailed development and security rules are maintained in [AGENTS.md](AGENTS.md). Project changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## Repository structure

```text
AIC/
|-- .github/
|   |-- ISSUE_TEMPLATE/       # Feature, bug, and improvement intake
|   |-- workflows/            # Continuous integration definitions
|   |-- CODEOWNERS            # Review ownership
|   `-- PULL_REQUEST_TEMPLATE.md
|-- docs/
|   |-- architecture/         # Architecture boundaries and reviews
|   |-- roadmap/              # Milestones and stage planning
|   |-- adr/                  # Architecture Decision Records
|   |-- api/                  # Future interface documentation
|   |-- database/             # Future data and migration documentation
|   |-- ui/                   # Future experience and interaction documentation
|   |-- development/          # Engineering workflow and repository practices
|   |-- deployment/           # Future release and operations documentation
|   |-- meeting/              # Decision-oriented meeting records
|   `-- research/             # Time-boxed investigations
|-- AGENTS.md                 # AI Development Handbook
|-- CHANGELOG.md              # Notable project changes
|-- CONTRIBUTING.md           # Contributor workflow
|-- PROJECT_ROADMAP.md        # Long-term stage roadmap
`-- README.md                 # Project entry point
```

Checkpoint 0 establishes governance only. It intentionally contains no business application, API, database, UI, infrastructure, market-data, or AI implementation.

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
uvicorn apps.backend.app.main:app --reload
```

The backend exposes only:

- `GET /` -> `{"project":"AIC","status":"running"}`
- `GET /health` -> `{"status":"healthy"}`

Run the health test with `pytest`.

## Start the Docker foundation

Copy `configs/environments/development.env.example` to a local `.env`, replace the placeholder password, then run:

```powershell
docker compose up --build -d
docker compose ps
```

This starts PostgreSQL, Redis, and the backend. The backend verifies both infrastructure connections before serving requests. Stop the environment with `docker compose down`; named data volumes are retained.

## Foundation structure

```text
apps/       Runnable desktop and backend applications
core/       Shared configuration, logging, exceptions, and utilities
shared/     Reserved cross-application contracts; no business objects yet
configs/    Environment configuration examples
docker/     Container build definitions
scripts/    Repository automation
tests/      Automated verification
docs/       Architecture and development documentation
.github/    CI and collaboration workflows
```
