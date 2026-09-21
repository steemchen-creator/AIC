# SPEC-011 Implementation Plan

Status: planning only — implementation is not authorized
Parent artifact: `SPEC-011-Global-Data-Fabric-and-Event-Intelligence-Foundation.md`
Engineering review: `REVIEW-SPEC011.md`

## Delivery rules shared by all checkpoints

Each checkpoint is independently reviewable, uses existing AIC boundaries and adds only the data
families needed by that checkpoint. Provider-specific fields terminate in adapters. Every persisted
fact is traceable to immutable raw evidence and a transformation version.

### Common domain model

Introduce a source-neutral `SourceLineage` value object for new evidence families:

| Field | Meaning |
| --- | --- |
| `adapter_id` | AIC-owned adapter implementation/configuration identity |
| `upstream_source_id` | Actual publisher/feed identity used for independence and authority |
| `authority_level` | `PRIMARY`, `HIGH_QUALITY_PUBLIC`, `RADAR`, or `COMMERCIAL` |
| `source_type` | `OFFICIAL_API`, `OFFICIAL_FEED`, `OFFICIAL_DOCUMENT`, `PUBLIC_MARKET_FEED`, `RADAR_FEED`, or approved extension |
| `source_uri` / `source_record_id` | Stable upstream locator where publication rules permit it |
| `event_time` | When the represented event/value applies |
| `published_at` | When the publisher released it, when known |
| `observed_at` | When AIC first successfully observed this version |
| `ingested_at` | When AIC durably stored it |
| `raw_hash` | Deterministic hash of canonical raw bytes/payload |
| `transformation_version` | Exact normalizer/schema version |

The canonical families are `MarketQuote`, `MarketPulseObservation`, `MacroObservation`,
`ScheduledEvent`, `SourceDocument` and `EventCandidate`. Each uses typed identity, immutable evidence
references and a quality assessment. They extend the current canonical model; they do not replace
`DailyBar`. `MarketPulseObservation` is a reference series and cannot be executed without a separate,
approved instrument/execution identity.

### Application ports

Add narrow ports, named around AIC use cases rather than vendors:

- `RawObservationRepository`
- `MarketQuoteRepository` and `MarketQuoteSourcePort`
- `MarketPulseRepository` and `MarketPulseSourcePort`
- `MacroObservationRepository` and `MacroSourcePort`
- `ScheduledEventRepository` and `ScheduledEventSourcePort`
- `SourceDocumentRepository` and `OfficialDocumentSourcePort`
- `EventCandidateRepository` and `EventRadarSourcePort`
- `AcquisitionPlanRepository` for application-owned cadence/checkpoint state
- `EvidenceQueryPort`

Provider adapters continue to be invoked and monitored through Provider Runtime. Repository ports
remain application-owned; PostgreSQL and in-memory implementations preserve existing parity rules.

### Capability IDs

| Capability | Mode / role |
| --- | --- |
| `market.quote.realtime` | Latest near-real-time observation; initially polling is allowed |
| `market.quote.snapshot` | Explicit bounded snapshot |
| `market.minute.read` | Historical/intraday minute observations |
| `market.index.snapshot` / `market.index.read` | Global equity-index level and history |
| `market.yield.snapshot` / `market.yield.read` | Sovereign curve points and history |
| `market.fx.snapshot` / `market.fx.read` | Currency reference/market rates and history |
| `market.commodity.snapshot` / `market.commodity.read` | Gold and crude-oil references/history |
| `market.volatility.snapshot` / `market.volatility.read` | Volatility benchmarks/history |
| `macro.series.read` | Series metadata and observation periods |
| `macro.release.read` | Release-calendar and release evidence |
| `macro.vintage.read` | Vintage/revision-aware observations |
| `calendar.event.read` | Current and historical scheduled-event versions |
| `calendar.event.changes` | Incremental schedule changes when the source supports a cursor |
| `official.document.read` | Fetch an identified official document/version |
| `official.feed.read` | Enumerate official release/document entries |
| `official.fiscal.read` | Fiscal-policy, budget, debt and treasury evidence |
| `official.trade.read` | Tariff, trade-policy and trade-statistics evidence |
| `official.sanctions.read` | Official sanctions lists, actions and amendments |
| `official.regulatory.read` | Regulatory rules, enforcement and consultations |
| `official.statistics.read` | National/supranational statistics releases |
| `official.energy.read` | Official energy supply, inventory and policy evidence |
| `official.issuer.read` | Listed-company IR and management statement evidence |
| `event.radar.read` | Discovery/radar candidate feed |

All IDs use the existing `ProviderCapability` contract and registry. A mapping from each Provider
Runtime capability to the existing data-ingestion capability type is explicit and tested.

### Source authority and factual confidence

Authority belongs to the upstream source. Operational provider health belongs to the adapter/runtime.
Factual confidence belongs to a reconciliation decision. These three values must never be conflated.

- Tier 0 / `PRIMARY`: official exchanges, regulators, governments, central banks and institutions.
- Tier 1 / `HIGH_QUALITY_PUBLIC`: public market feeds such as Eastmoney, Sina and Tencent.
- Tier 2 / `RADAR`: discovery-only feeds such as GDELT.
- Tier 3 / `COMMERCIAL`: paid/contracted enhancement sources.

Two observations can vote independently only when their `upstream_source_id` differs. An adapter
failure is recorded through existing runtime health. A fact conflict is recorded through the quality
and reconciliation model.

### PIT semantics

A record is eligible for an `as_of` query only if all family-specific availability timestamps are
known and no later than `as_of`:

- Quotes: upstream/source time when reliable, plus `observed_at`; operational replay also requires
  `ingested_at` no later than `as_of`.
- Macro: official `release_at`/`published_at`, selected vintage availability and `observed_at`.
- Market pulse: benchmark/source time plus `observed_at`; a daily official value cannot be presented
  as realtime, and a later corrected benchmark appends a version.
- Scheduled events: the schedule version's `published_at` and `observed_at`; `scheduled_for` is the
  subject of the fact, not its availability time.
- Documents: `published_at` and `observed_at`; a later correction is a new version.
- Radar events: discovery `observed_at`; their underlying event time alone never makes them
  historically available.

Unknown availability fails closed in historical research. Latest revised macro values require an
explicit non-PIT query; they cannot silently replace the vintage known at the requested time.

## Continuous Data Acquisition Orchestration

Continuous acquisition is an application service above Provider Runtime. It decides when and what
scope to request, then invokes the existing Runtime for registration, selection, health, capacity,
cooldown, timeout and bounded failover. It never calls adapters directly and does not maintain a
parallel provider registry, score or failover policy.

### Cadence policy and job kinds

An immutable, versioned `AcquisitionPlan` binds capability, subject scope, freshness objective,
upstream constraints, timezone/session calendar, priority and one cadence policy:

- fixed interval for continuously changing snapshots;
- market-session-aware polling for quotes and pulse indicators;
- official release-window polling around a `ScheduledEvent`;
- feed/cursor polling for RSS, filings and incremental APIs;
- periodic reconciliation/repair for delayed documents and revisions; or
- bounded backfill for a declared historical interval.

The scheduler computes due work from the plan and durable checkpoint. It does not infer that a
provider succeeded from elapsed time or from an HTTP response alone.

### Durable checkpoint and multi-worker safety

An `AcquisitionCheckpoint` records plan/version, capability/scope, source cursor or high-watermark,
last attempted/successful request, last durably persisted observation, last source timestamp,
consecutive failures, retry/backoff deadline, source rate-limit state and an expiring lease with a
fencing token. PostgreSQL atomically claims a due job. In-memory storage exists for parity tests only.

The success sequence is:

1. claim a due job and capture its fencing token;
2. calculate one bounded request/page/window from the durable cursor/watermark;
3. invoke Provider Runtime with the capability and source constraints;
4. normalize, validate and durably persist raw/canonical evidence idempotently;
5. advance the checkpoint in the same durable completion boundary; and
6. calculate the next due time from cadence, freshness, provider cooldown and rate-limit evidence.

A stale worker cannot advance a checkpoint after its lease is lost. A cursor never advances past a
failed persistence operation.

### Catch-up, backfill and failure recovery

- Cursor sources resume from the last committed cursor. Time-range sources resume from the last
  complete watermark with a bounded overlap window.
- Catch-up is page/window bounded, oldest-first unless the approved source contract requires another
  deterministic ordering, and yields to higher-priority fresh work.
- Deterministic observation IDs make replay safe; changed payloads append a new source version.
- Retryable failures preserve the cursor and use bounded exponential backoff plus provider
  `Retry-After`, quota and cooldown signals. Non-retryable schema/identity failures quarantine the
  item and open an actionable incident rather than skipping it.
- When downtime exceeds the online catch-up budget, the same plan creates bounded backfill work and
  reuses existing backfill-attempt/coverage concepts.
- Feed connections use an upstream resume token where supported. Without one, reconnect performs a
  bounded overlap poll and relies on idempotent identity; heartbeats feed existing provider health.

Tests use a controlled clock and deterministic backoff inputs. They cover crash points before and
after evidence persistence/checkpoint advance, lease loss, duplicate delivery, cursor invalidation,
rate-limit exhaustion, long outage catch-up and multi-worker competition.

## Checkpoint A — Realtime Market Data

### A0 — Shared lineage and ingestion extension

- Add `SourceLineage` and immutable raw-observation persistence.
- Generalize normalizer/validator/quality dispatch for typed canonical families while preserving
  current DailyBar behavior.
- Register quote capability IDs through Provider Runtime.
- Extend PIT dispatch for quote observations.

### A1 — Quote domain and persistence

- Add source-neutral `MarketQuote`: canonical instrument identity, bid/ask, last, previous close,
  volume/turnover, source/event timestamps, lineage and quality.
- Resolve A-share Equity, domestic ETF and index-reference identities through existing instrument,
  ETF and index foundations. Unknown or contradictory identity fails closed.
- Persist every source observation and canonical reconciliation decision with deterministic IDs and
  idempotent inserts.

### A2 — Production adapters

- Add separately identified Eastmoney, Sina and Tencent adapters behind the existing Provider Runtime.
- Use the existing HTTP boundary, explicit timeout, bounded retry/failover policy, sanitized errors,
  payload limits and deterministic fixtures.
- Keep Tushare for daily/reference capabilities. Do not count libraries, caches or fallbacks that
  share an upstream as independent sources.

### A3 — Independent-source reconciliation

- Fetch a configured bounded set of independent upstream observations through Provider Runtime.
- Normalize comparable units/timestamps, reject impossible identity or numeric values, then compare
  price, timestamp, session status and optional volume/turnover with approved tolerances.
- Emit an immutable reconciliation record with contributing observation IDs, missing/stale/conflict
  reasons, confidence and chosen value policy.
- If quorum is absent, return a degraded/unknown result. Capital-affecting consumers fail closed;
  research consumers may receive the observations and explicit quality flags.

### A4 — Tests and operations

- Contract fixtures for all three upstreams, malformed/truncated/empty/rate-limited responses and
  timestamp/encoding edge cases.
- Deterministic independence tests proving AKShare(Eastmoney) and efinance(Eastmoney) are one vote.
- Reconciliation permutation tests, stale-source tests, restart/idempotency tests, PostgreSQL
  round-trip and reversible-migration tests.
- Provider health/failover tests proving a transport fallback cannot fabricate consensus.
- Live smoke tests remain opt-in and never gate deterministic CI.

Expected checkpoint result: a PIT-safe, auditable domestic quote foundation with bounded degraded
behavior. It does not authorize live trading decisions by itself.

## Global Cross-Asset Market Pulse roadmap

The pulse is a capability universe spanning checkpoints rather than a commitment to implement every
source in Checkpoint A. A shared `MarketSeriesIdentity` identifies family, benchmark owner, geography,
currency/quote unit, tenor or contract/reference definition. `MarketPulseObservation` records value,
source/event time, observed/ingested time, lineage, freshness and quality.

| Family | Initial universe | Delivery placement |
| --- | --- | --- |
| Global equity indexes | S&P 500, Nasdaq-100, DJIA, STOXX Europe 600, FTSE 100, DAX, Nikkei 225, TOPIX, Hang Seng, CSI 300/SSE Composite and other approved regional benchmarks | Model/capabilities in A; licensed/delayed adapters added in approved A extensions |
| Sovereign yields | US, euro-area/Germany, UK, Japan and China benchmark curves at policy-relevant tenors | Official daily series in B; realtime licensed enhancement later if justified |
| FX | DXY or an approved trade-weighted equivalent; USD/CNY, EUR/USD, USD/JPY, GBP/USD and other policy-relevant pairs | Official reference rates in B; market snapshots in an approved A extension |
| Gold | LBMA benchmark/reference and an approved market proxy where licensed | Daily/reference in B; realtime only with explicit license |
| Crude oil | WTI and Brent spot/benchmark, inventories and selected futures reference where licensed | EIA official data in B; exchange realtime enhancement later |
| Volatility | Cboe VIX and approved regional/rates/commodity volatility benchmarks | Official historical/delayed or licensed source; no prohibited page scraping |

Pulse reconciliation compares only the same benchmark definition, timestamp basis, currency/unit and
licensing mode. Related but different indexes or yields can coexist in an Evidence Pack but do not
vote on one another. Checkpoint D assembles a PIT-safe pulse view with explicit market-open state,
staleness and coverage so downstream consumers can interpret transmission across time zones.

Regression tests cover benchmark/tenor/unit mismatch, cross-time-zone freshness, daily-versus-
realtime labeling, PIT visibility, licensed-source metadata and an architecture/risk assertion that
a reference-only pulse identity cannot enter execution as a tradable instrument.

## Checkpoint B — Global Macro and PIT

### Domain and ports

- Add `MacroSeriesIdentity`, `MacroObservation`, `MacroRelease` and explicit vintage/revision identity.
- Add `ScheduledEvent` with event type, subject/geography/series or issuer references, scheduled
  time/window and timezone, status, version/predecessor identity, source lineage and actual-evidence
  links.
- Keep units, seasonal adjustment, geography, frequency and observation period typed and validated.
- Add source-neutral macro ports and repositories; do not expose FRED or SDMX field names to Domain.

### Adapters

1. FRED/ALFRED direct official API adapter, including realtime periods and vintage dates.
2. Generic, bounded SDMX transport/parser shared by separate OECD, IMF and BIS adapters.
3. Optional ECB Data API adapter for first-wave rates/FX/monetary series where the ECB is primary.
4. Official economic/policy calendar adapters beginning with central-bank meeting calendars, BLS,
   BEA and publisher release schedules; FRED release dates supplement historical release identity.

The generic SDMX code handles protocol mechanics only. Dataset IDs, authority and transformations
remain adapter-owned so that a generic client does not become a second provider registry.

### Persistence and PIT

- Store series definitions separately from immutable observations and vintages.
- Preserve the official release timestamp, vintage/revision timestamp, first observation time and
  raw source link/hash.
- Query modes are explicit: `KNOWN_AT(as_of)`, `AS_PUBLISHED(vintage)` and `LATEST_REVISED`.
- Revision chains append; they never update the prior value in place.
- Schedule publication, reschedule, cancellation and completion append immutable versions. When the
  release occurs, link the scheduled event to the resulting `MacroObservation` and/or
  `SourceDocument`; do not replace the calendar record with the actual result.

### Tests and failure behavior

- Golden SDMX JSON/CSV and FRED fixtures; unit/frequency/geography mismatch rejection.
- ALFRED revision tests proving a historical query cannot see later revisions.
- Delayed ingestion, date-only release, duplicate vintage and missing timestamp negative tests.
- Schedule revision/PIT tests proving a historical query sees the time known then, plus deterministic
  linkage from the schedule to an actual release/document.
- Institution-specific rate-limit, schema drift and empty-series behavior.
- PostgreSQL restart, idempotency and migration round-trip tests.

An unavailable institution degrades only its configured series. No alternate publisher may silently
substitute for an official macro series with a different definition.

## Checkpoint C — Policy, People and Event Intelligence

Implementation status (2026-09-22): the source-neutral document/entity/event foundation,
Federal Reserve RSS, SEC EDGAR, discovery-only GDELT adapters and PostgreSQL migration 0018 are
implemented for review. The remaining source universe stays on the roadmap and Checkpoint D has
not started.

### Domain and ports

- Add `SourceDocument`, immutable `DocumentVersion`, `EventCandidate`, `EntityIdentity` and explicit
  source-document/event links.
- Store publisher, document type, title, language, speaker and source-declared role, event/published/
  observed/ingested timestamps, source URI/ID, content hash and supported supersession identity.
- Keep interpretation, sentiment and investment conclusions outside this data layer.

### Official adapters

- Fed releases/RSS/FOMC pages, ECB RSS/Data/MID publications, BOJ RSS/pages and PBOC official pages.
- Fiscal and debt authorities; finance ministries/treasuries; official budget, tax, auction and debt
  publications.
- Trade and sanctions authorities including customs/trade ministries, WTO/UN Comtrade, OFAC and
  equivalent EU/UK/UN authorities.
- Securities, banking, competition and market regulators; official statistics agencies; EIA/IEA/
  OPEC and other primary energy authorities; IMF, World Bank, BIS, OECD and other international
  institutions.
- SEC EDGAR official submissions/XBRL/file APIs with declared User-Agent and rate limits.
- CNINFO official disclosure pages/files after access and production-use terms are documented.
- Listed-company IR/management statements and official exchange announcement services. Issuer pages
  are Tier 0 only when canonical issuer identity and official-domain control are verified.
- GDELT as `RADAR` discovery only.

### Verification and entity resolution

- Promote official documents directly at Tier 0 after identity/hash/metadata validation.
- Link radar candidates to official documents without mutating either item.
- Link issuer earnings/meeting schedules to the actual filing, release, transcript/statement or
  cancellation while preserving every schedule version.
- Resolve institutions, people and issuers by official identifiers and reviewed alias tables.
  Ambiguous matches remain unresolved candidates.
- A later correction/supersession appends a new version and relation; audit history is immutable.

### Tests and failure behavior

- Feed pagination, conditional requests, revised documents, removed links, duplicate content and
  malicious/oversized markup/XML fixtures.
- SEC issuer/form/accession consistency and CNINFO issuer/security consistency fail closed.
- Sanctions-list amendments, fiscal/trade document revisions, official-calendar changes and issuer
  domain/identity mismatches fail closed or remain unverified candidates.
- GDELT cannot establish or overwrite a Tier-0 fact.
- Entity collision, multilingual title and unknown-speaker-role tests.
- PostgreSQL restart, idempotency, PIT visibility and migration round-trip tests.

A failed radar or feed adapter does not erase prior evidence. A fetched document with unverifiable
publisher/identity is quarantined from canonical promotion with an actionable quality reason.

## Checkpoint D — Evidence Query Layer

### Evidence Pack contract

Add an application-owned, read-only `EvidencePack` query interface for Market Regime, Opportunity
Radar, Research and the AI Investment Committee. A pack contains:

- query identity, `as_of`, availability context and requested capabilities;
- immutable references to selected canonical observations and raw lineage;
- excluded/conflicting evidence summaries;
- reconciliation/quality/confidence evidence;
- scheduled-versus-actual event links and the global cross-asset pulse appropriate to `as_of`;
- freshness and coverage; and
- the transformation/query policy versions needed to reproduce it.

Consumers request source-neutral evidence by instrument, series, entity, time range and capability.
They cannot call vendor adapters or bypass PIT policy. The service returns partial/degraded evidence
explicitly and fails closed when a required minimum is absent.

### Tests and failure behavior

- Cross-family PIT/no-lookahead tests and deterministic serialization/hash tests.
- Query replay after PostgreSQL restart.
- Source withdrawal, conflicting evidence, stale data and partial-provider failure tests.
- Architecture tests preventing domain/application imports from provider or infrastructure modules.
- Consumer contract tests for Regime, Radar, Research and Committee without implementing those
  product features in SPEC-011.

Checkpoint D should initially be a query DTO/projection and need no persistence table. Add snapshot
persistence only if a later approved consumer requires durable pack materialization.

## Expected migrations

Migration numbers are allocated only at implementation time from the then-current main branch.
The expected logical sequence is:

1. **A:** immutable raw/source observations, market quotes, pulse-series definitions/observations,
   reconciliation decisions and their source-observation links; indexes on identity/event time,
   observed time, upstream source and deterministic IDs.
2. **Acquisition:** versioned acquisition plans, durable checkpoints, cursor/watermark state,
   rate-limit/backoff evidence and fenced job leases. This can share A's migration only if review
   confirms a coherent reversible boundary.
3. **B:** macro series definitions, observations, release/vintage identities, scheduled-event
   versions, actual-evidence links and revision relationships; uniqueness across
   series/period/vintage/upstream.
4. **C:** source documents, document versions, entities/aliases, event candidates and evidence links.
5. **D:** no migration expected for the initial query projection.

Every migration must be reversible and covered by empty/populated upgrade, downgrade and round-trip
tests. Downgrade removes newly stored evidence and is therefore destructive; production execution
requires backup/export, an explicit maintenance plan and separate authorization.

## Expected changed files

Exact paths may be refined after the authorized checkpoint starts. The anticipated surfaces are:

- `apps/backend/src/aic_backend/domain/market_data/` for `MarketQuote`, pulse series and shared data lineage;
- `apps/backend/src/aic_backend/domain/evidence/` for macro, scheduled-event, document and event models;
- `apps/backend/src/aic_backend/application/ports/` and focused application services;
- `apps/backend/src/aic_backend/application/acquisition/` for cadence policy, durable job orchestration
  and catch-up coordination over Provider Runtime;
- `apps/backend/src/aic_backend/data_foundation/` normalizer, validation and quality extensions;
- `apps/backend/src/aic_backend/provider_runtime/` capability/result attribution extensions only;
- `apps/backend/src/aic_backend/providers/` source-specific adapters;
- `apps/backend/src/aic_backend/infrastructure/` PostgreSQL repositories;
- `apps/backend/src/aic_backend/bootstrap/` production composition;
- `apps/backend/migrations/` reversible checkpoint migrations;
- corresponding unit, architecture, PostgreSQL integration and migration tests;
- capability/source documentation, ADR if an accepted architecture decision changes, README and
  changelog entries required by repository policy.

## Acceptance gates for each implementation checkpoint

- Deterministic unit and contract tests, negative paths and source independence.
- PostgreSQL 17 full suite, persistence/restart and idempotency.
- Migration upgrade/downgrade/round-trip when schema changes.
- PIT/no-lookahead and reconciliation evidence.
- Controlled-clock cadence, durable cursor/watermark, rate-limit, crash/restart and multi-worker
  lease/fencing tests for continuously acquired capabilities.
- Architecture tests, Ruff, strict mypy, repository coverage gate and `git diff --check`.
- Exact-HEAD CI and required Governance Gate, without weakening existing policy.
