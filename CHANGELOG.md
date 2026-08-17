# Changelog

All notable changes to the AIC project are documented in this file.

The project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- SPEC-004 Phase 10 canonical corporate-action and adjustment-factor facts, dedicated
  Provider capabilities, deterministic normalizers and idempotent PostgreSQL persistence.
- Explicit RAW, forward-adjusted and backward-adjusted DailyBar projections with complete
  factor coverage enforcement, raw OHLC preservation and unchanged volume/turnover.
- Resumable adjustment-factor backfill, explicit corporate-action sync, migration and
  Runtime-to-PostgreSQL-to-Historical deterministic E2E evidence.

- SPEC-004 Phase 9 canonical A-share Instrument Master and daily trading-status facts,
  explicit Tushare sync/backfill, PostgreSQL persistence and operational coverage.
- Evidence-gated Historical DailyBar classification for market closure, listing
  lifecycle, explicit suspension and probable data gaps.

- SPEC-004 Phase 8 canonical SSE/SZSE trading-calendar facts, standard split-session
  policy, Calendar Provider capability, PostgreSQL repository/coverage and explicit sync.
- Calendar-aware Historical DailyBar candidate-gap detection that excludes confirmed
  CLOSED dates while preserving the unresolved instrument-suspension limitation.

- SPEC-004 Phase 7 inclusive historical A-share DailyBar queries, conservative
  coverage/gap detection and explicit sequential backfill through the existing Runtime.
- Persistent backfill-attempt ledger, configurable date chunking, partial-failure resume,
  deterministic ordering, PostgreSQL E2E and concurrent idempotency evidence.

- SPEC-004 Phase 6 Tushare Pro A-share daily Provider, Runtime-selected ingestion,
  canonical unit conversion, partial batch processing, and idempotent persistence.
- Reversible canonical `record_id` length migration aligning PostgreSQL storage with
  the existing deterministic identity contract.

- SPEC-004 Phase 5 Application-owned persistence port, idempotent PostgreSQL adapter,
  immutable ingestion-time quality snapshots and Alembic schema migration.
- PostgreSQL contract, concurrency, transaction, read-back and migration tests with
  exact NUMERIC financial values and stable persistence errors.
- SPEC-004 Phase 4 deterministic Raw-to-Canonical normalization and ingestion pipeline
  with immutable structured outcomes and explicit fixture-normalizer registration.
- Provenance-preserving DailyBar parsing plus existing Validation/Quality integration,
  100-run determinism, no-mutation and architecture-boundary evidence.
- SPEC-004 Phase 3 deterministic Data Quality Engine with fixed explainable weighting,
  immutable assessments/flags and validated-input enforcement.
- DailyBar freshness, completeness, consistency and configurable source-confidence
  policies plus exact Decimal conflict representation without reconciliation.
- Quality identity-stability, no-mutation, 100-run determinism, 10,000-assessment and
  architecture-isolation tests without changing Provider Runtime Quality Score.
- SPEC-004 Phase 2 deterministic Validation Engine with immutable issues/results,
  injected-clock timestamp rules and explicit CanonicalRecord/DailyBar dispatch.
- Structural validation for schema, timestamps, instruments, provenance and safe
  payloads plus DailyBar OHLC, non-negative price, volume and turnover rules.
- Validation purity, determinism, no-auto-correction, architecture-boundary and
  10,000-record calculation tests without introducing Quality or persistence.
- SPEC-004 Phase 1 immutable real-data models for market-qualified instruments,
  canonical envelopes, typed daily bars, raw observations and source provenance.
- Deterministic SHA-256 record identity and canonical raw-payload hashing with
  timezone-safe semantics, Decimal financial values and deep immutable mappings.
- Automated SPEC-004 Phase 1 architecture boundaries and identity, timestamp,
  provenance, hashing, immutability and serialization tests.
- SPEC-003 Provider Runtime immutable models, lifecycle and invocation
  protocols, stable errors, and injectable UTC clock and UUID generation.
- ADR-0003 and automated Provider Runtime dependency boundaries.
- Ruff, Mypy, and branch-aware pytest coverage quality checks.
- Concurrency-safe Provider Registry, immutable registration snapshots,
  validated Provider Definitions, and an explicit allowlist Provider Factory.
- Provider Lifecycle and Health Managers with validated serialized state
  transitions, bounded checks, deterministic thresholds, cancellable monitoring,
  and lifecycle events on the existing Event Bus.
- Deterministic Provider selection with structured exclusion reasons, preferred
  ordering, read-only capacity and cooldown inputs, and explainable weighted
  quality scoring.
- Single-Provider invocation with immutable requests and standardized results,
  call-level timeout, cancellation propagation, sanitized errors, and guaranteed
  concurrency-capacity release.
- Bounded Provider failover with an explicit error allowlist, Selector-based
  backup ordering, non-repeating attempts, structured exhaustion errors, and
  final-source attempt attribution.
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
- Architecture audit remediation for isolated Mock fixtures, validated immutable
  Domain Events, expanded dependency-rule tests, and explicit liveness semantics.

### Changed

- Expanded `AGENTS.md` into the AIC AI Development Handbook.
- Documented the governed repository structure in `README.md`.
- Migrated the Python backend to the `apps/backend/src/aic_backend` package and
  updated Docker and test discovery paths.
