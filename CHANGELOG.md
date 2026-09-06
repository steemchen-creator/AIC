# Changelog

All notable changes to the AIC project are documented in this file.

The project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- DEV-GOV-001 isolated development control plane: versioned state/events, atomic local
  and GitHub state-branch persistence, exact SHA/CI gates, budgeted artifact/task bridges,
  deterministic merge/closeout, governance incident handling and restart recovery.
- Read-only AIC Development Governance Gate, per-module coverage enforcement, project
  memory, proposed ADR-0007 and Chairman setup documentation. Bootstrap/manual-only;
  pipeline/auto-merge/external API activation remain disabled and SPEC-010 is not started.

- FIX-SPEC009-002 governance exception for the premature merge of PR #10,
  including tree equivalence, exact feature-head CI, fresh main regression,
  impact assessment, prevention rules, and post-publication closeout requirements.
- FIX-SPEC009-003 separates remediation execution authorization from external
  Architecture Approval, marks the record `REVIEWED_PENDING_PUBLICATION`, and
  requires human merge of PR #11 plus main verification before formal closeout.
  Missing main branch protection / approval enforcement remains non-blocking
  governance hardening debt; administrator settings are unchanged.

- SPEC-009 境内 ETF 与指数参考基础：来源中立的 ETF Master、QDII/底层暴露元数据、
  ETF-index relationship、指数参考、ETF/Index DailyBar、Adjustment Factor 与估值快照。
- Tushare ETF/指数显式 Provider capability 与严格 Normalizer，包含手/份、千元/元、万份/份
  单位转换、确定性 RawObservation/provenance、空结果 coverage 语义和 PostgreSQL 可逆迁移 0013。
- 产品级 PIT Execution Profile、T0/T1/Unknown 安全规则、asset-aware fee/tax、指数不可交易门禁，
  以及 Champion/Shadow 的 Equity+ETF CNY 混合组合、账户隔离与无未来数据泄漏证据。

- SPEC-008 架构审计整改：新增可审计的角色头像引用更新、Role Activity Board 当前状态投影、
  处理顺序独立性与中断后幂等恢复证明，以及 Shadow 关键模块 95% 以上分支覆盖率门禁证据。
- 可逆迁移 0012 与 `shadow_role_profile_events` 追加式审计表；头像变化不改写不可变 Manifest、
  Portfolio、Account、NAV、Order、Fill、Decision 或 Track Record。

- SPEC-008 Champion 与至少三个 Shadow Portfolio 的公平实验组，包含独立账户、组合状态、
  连续复利、Decision Source assignment、Group Trading Session 和单成员故障隔离。
- 不可变 Experiment Manifest、Fairness Contract 与规范化 Policy Bundle Hash，冻结 PIT、日历、
  执行、风控、费率、滑点、Benchmark、初始资金和开始日期。
- 多维 Performance Comparison、短样本保护、确定性 Leaderboard、真实 Role Activity 聚合以及
  AssetClass/MarketVenue/Currency 多资产兼容元数据。
- Application-owned Experiment Port、PostgreSQL 恢复投影与规范化证据、可逆迁移 0011、
  独立性/重启/故障隔离/架构边界测试。

- SPEC-007 forward-only Paper Trading Runtime and official 500,000 CNY Champion Portfolio,
  with explicit activation, pause/resume/stop, trading-session state machines and continuous
  compounding without daily capital reset.
- OPERATIONAL_REPLAY/PIT-only NEXT_OPEN execution, closing mark-to-market, conservative
  missing-data/corporate-action blocking and reuse of SPEC-006 A-share execution and risk.
- Immutable daily performance, drawdown, benchmark, cost and closed Trade Episode evidence,
  atomic restart recovery, four crash checkpoints and deterministic idempotency tests.
- Application-owned Paper ports, PostgreSQL persistence, reversible migration 0010,
  architecture boundaries and Paper Runtime/Domain/Persistence coverage gates.

- SPEC-006 deterministic A-share cash-account execution and pre-trade risk foundation,
  including PIT session/instrument eligibility, conservative unknown handling and stable
  acceptance/rejection evidence.
- T+1 total/sellable/today-bought quantity tracking with Trading Calendar-gated rollover,
  board-lot and explicit price-limit policies, suspension handling and no-short invariants.
- Configurable concentration, gross-exposure, cash-buffer, daily order/fill/turnover guards,
  post-trade risk snapshots and versioned execution/risk policies without hidden leverage.
- Application-owned execution evidence port, PostgreSQL insert-or-verify adapter, reversible
  migration 0009, deterministic E2E, PIT/no-lookahead and architecture-boundary tests.

- SPEC-005 deterministic daily backtest and multi-position portfolio accounting foundation
  with PIT-only RAW market-data access and trading-calendar replay.
- Immutable order/fill/audit facts, cash ledger, weighted-average position accounting,
  realized/unrealized PnL, daily NAV, benchmark and transparent fee/tax/slippage results.
- Application-owned backtest persistence port, normalized PostgreSQL evidence tables,
  reversible migration 0008, deterministic E2E and no-lookahead architecture tests.

- SPEC-004 Phase 11 immutable Point-in-Time context/results, versioned availability policy
  and Application-owned market-data façade for DailyBars, actions, factors, instruments,
  trading status and calendar facts.
- Historical Research versus Operational Replay semantics, explicit Unknown classification,
  conservative instrument-universe controls and RAW-only PIT price access.
- Nullable provider-availability provenance round-trip and PIT indexes via migration 0007;
  existing rows remain Unknown rather than receiving fabricated availability timestamps.

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
