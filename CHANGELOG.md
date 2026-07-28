# Changelog

All notable changes to the AIC project are documented in this file.

The project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Repository governance rules covering branches, checkpoints, commits, Pull Requests, documentation, sensitive files, and architecture changes.
- Baseline ignore rules for secrets, logs, caches, generated output, and local tooling.
- Project Governance documentation tree for architecture, roadmap, ADRs, APIs, databases, UI, development, deployment, meetings, and research.
- ADR lifecycle and review policy in ADR-0000.
- Project roadmap, milestone plan, contributor guide, GitHub templates, ownership rules, and CI workflow foundation.
- Checkpoint 1 engineering foundation with a .NET 8 WPF shell and Python 3.12 FastAPI shell.
- Unified environment configuration, structured logging, application exceptions, and infrastructure connection boundaries.
- PostgreSQL, Redis, backend Docker Compose topology and Celery initialization.
- Backend health test and CI jobs for Python tests and the Windows desktop build.
- ADR-0001 documenting the approved foundation architecture, impact, risks, and controls.
- Clean Architecture Data Foundation package with Domain, Application,
  Presentation, Provider, Infrastructure, Bootstrap, and Shared boundaries.
- Framework-independent data record and event contracts.
- Mock Provider plus in-memory Repository, Cache, and Event Bus adapters.
- Source-neutral Data Foundation API and deterministic unit, integration, and
  architecture dependency tests.
- TASK-002 architecture, domain, provider, repository, API, testing, and
  acceptance documentation.

### Changed

- Expanded `AGENTS.md` into the AIC AI Development Handbook.
- Documented the governed repository structure in `README.md`.
- Migrated the Python backend to the `apps/backend/src/aic_backend` package and
  updated Docker and test discovery paths.
