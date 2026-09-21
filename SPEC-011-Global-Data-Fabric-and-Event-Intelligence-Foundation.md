# SPEC-011 — Global Data Fabric & Event Intelligence Foundation

Version: 0.9 Draft
Status: ARCHITECT PREPARED — START AFTER SPEC-010 CLOSEOUT
Owner: Chief Investment Architect
Product priority: HIGH

## 1. Purpose

SPEC-011 makes AIC continuously aware of the financial world.

The system must move beyond a local A-share historical-data foundation and ingest, normalize,
validate, timestamp, reconcile and query a global information set that can later feed Opportunity
Radar, Market Regime, Research, Evidence Packs and the AI Investment Committee.

The first implementation must cover both:

1. real-time / near-real-time market observation; and
2. macro, central-bank, policy, official-document and event intelligence.

These two tracks are parallel. Stock-market interfaces are not deferred.

## 2. Product principle

Governance is a guardrail, not the product.

Reuse the existing Provider Runtime, Data Foundation, Validation, Quality, PIT, Provenance,
PostgreSQL and failover infrastructure. Do not create a second data stack.

Only correctness, data lineage, PIT/no-lookahead, capital-safety or irreversible evidence-loss
issues may block delivery. Non-critical edge cases should be recorded as technical debt and must
not create unbounded review loops.

## 3. Existing foundation to preserve

SPEC-011 must reuse the current repository capabilities:

- Provider Runtime registration, lifecycle, health, quality scoring, selection, invocation and bounded failover;
- RawObservation / Canonical data model and deterministic identity;
- Validation Engine;
- Data Quality Engine;
- normalization and ingestion pipeline;
- PostgreSQL canonical persistence;
- trading calendar, instrument master and trading status;
- corporate actions / adjustment factors;
- PointInTimeMarketDataService and no-lookahead policy;
- existing Tushare production adapter;
- existing A-share / ETF / index / execution foundations.

No provider-specific field may leak into source-neutral Domain models.

## 4. Source acquisition rule

Whenever a new external capability is required, Engineering must first inspect:

1. the authoritative upstream source and official API / RSS / SDMX / data feed where available;
2. high-quality GitHub projects that expose, document or implement the capability;
3. maintenance activity, upstream lineage, license, stability and failure modes;
4. whether direct upstream HTTP access is safer than importing a large third-party SDK/library.

Priority order:

Official upstream > verified direct public endpoint > high-quality open-source adapter > paid provider.

A GitHub project's Star count is never sufficient evidence of data quality.

Every adapter must separately identify:

- `adapter_id` — AIC implementation/provider identity;
- `upstream_source_id` — actual source of the fact, e.g. EASTMONEY, SINA, TENCENT, FRED;
- `authority_level`;
- source URI / document ID where permitted;
- event/published/observed/ingested timestamps;
- raw payload hash and transformation version.

Two libraries using the same upstream source do not count as two independent confirmations.

## 5. Source authority tiers

### TIER 0 — Primary authority

Official exchanges, regulators, governments, central banks and international institutions.
Examples:

- SSE / SZSE / BSE / CNINFO / CSRC;
- Federal Reserve / FRED / ALFRED;
- ECB / BOJ / PBOC / BOE;
- US Treasury / SEC EDGAR / BLS / BEA / CFTC / EIA;
- IMF / BIS / OECD / World Bank;
- official index providers where licensed/available.

Tier 0 is preferred for rules, policy decisions, official releases, filings and macro facts.

### TIER 1 — High-quality free/open market feeds

Initial candidates found during Architecture scouting:

- `akfamily/akshare`;
- `Micro-sheep/efinance`;
- `shidenggui/easyquotation`;
- `1nchaos/adata`.

These are discovery/reference candidates, not automatic production dependencies.
Where feasible, production adapters should target the actual upstream endpoint directly and retain
upstream identity.

Initial independent market upstreams:

- EASTMONEY;
- SINA;
- TENCENT;
- optionally BAIDU/other source only after validation.

### TIER 2 — Event radar / discovery

- GDELT 2.x and equivalent event/news discovery sources.

Tier 2 can create an EventCandidate but cannot by itself establish a high-authority policy fact.
Important events should be verified against Tier 0 or multiple independent sources where possible.

### TIER 3 — Commercial enhancement

Examples: Tushare paid capabilities, JQData, RQData, Choice, Wind, licensed Level-2/Tick feeds.

Commercial sources are added only when free/official sources cannot meet the required latency,
history, PIT, completeness, licensing or SLA.

## 6. First delivery capabilities

### 6.1 Market observation

Add source-neutral Provider Runtime capabilities for at least:

- `market.quote.realtime`
- `market.quote.snapshot`
- `market.minute.read`
- existing daily-bar capabilities remain unchanged

V1 must support A-share Equity, domestic ETF and index-reference observation.

Initial implementation target:

- EASTMONEY real-time quote adapter;
- SINA real-time quote adapter;
- TENCENT real-time quote adapter;
- existing Tushare remains historical/daily/reference data source.

GitHub libraries may be used as implementation references or adapters if Architecture determines
that importing them is lower risk than direct access.

### 6.2 Macro and economic time series

Add capabilities such as:

- `macro.series.read`
- `macro.release.read`
- `macro.vintage.read`

First official adapters:

- FRED / ALFRED;
- OECD SDMX;
- IMF SDMX;
- BIS SDMX.

ALFRED-style revision/vintage semantics are first-class. AIC must distinguish the value known at
a historical date from today's revised value.

### 6.3 Official policy and speech documents

Add:

- `official.document.read`
- `official.feed.read`

Initial publishers should include central-bank and policy sources such as Fed, ECB, BOJ and PBOC,
subject to available official feeds/pages.

Canonical document evidence must preserve:

- publisher/institution;
- title;
- document type;
- original language;
- speaker where applicable;
- speaker role where explicitly known from source;
- event time;
- publication time;
- observed/retrieved time;
- canonical source URL or document identity;
- immutable content hash;
- revision/supersession identity where detectable.

AIC must not infer political intent or investment direction in the data layer.

### 6.4 Company filings and announcements

Initial authoritative sources:

- CNINFO for China listed-company disclosure where accessible;
- SEC EDGAR for US filings / XBRL / submissions.

GitHub scouting found `dgunning/edgartools` and `sec-edgar/sec-edgar` as useful implementation
references, but the preferred authority remains SEC's official API/file system.

### 6.5 Event radar

Add:

- `event.radar.read`

First candidate: GDELT.

GDELT observations are discovery evidence and must carry `RADAR` authority. They can trigger
verification work but cannot overwrite a conflicting Tier-0 fact.

## 7. Canonical models

Do not force all global information into DailyBar.

Introduce the minimum source-neutral canonical families required:

### MarketQuote

Minimum fields:

- instrument identity;
- bid/ask where supplied;
- last price;
- previous close where supplied;
- volume / turnover where supplied;
- source timestamp;
- observed_at / ingested_at;
- provenance;
- quality assessment.

### MacroObservation

Minimum fields:

- series identity;
- geography;
- publisher/source;
- observation period;
- value/unit;
- release_at;
- vintage/revision timestamp when available;
- observed_at / ingested_at;
- provenance.

### SourceDocument

Minimum fields:

- document id;
- publisher;
- document type;
- title;
- canonical source URI;
- event/published/observed/ingested timestamps;
- speaker + explicit role when applicable;
- language;
- content hash;
- raw/normalized text linkage;
- provenance.

### EventCandidate

Minimum fields:

- event id;
- event category;
- event timestamp;
- detected_at;
- entities/locations explicitly supplied or deterministically resolved;
- source-document IDs;
- authority/confidence state;
- verification status.

EventCandidate is evidence, not an investment recommendation.

## 8. Source lineage and independence

Add upstream-source identity to provenance or an adjacent source-lineage model.

AIC must be able to distinguish:

`AKShare -> EASTMONEY`

from

`efinance -> EASTMONEY`.

These are two adapters but one upstream vote.

Cross-source confirmation counts independent upstreams, not Python packages.

## 9. Market reconciliation

Implement a deterministic quote-reconciliation service above validated source observations.

V1 policy:

- never average obviously conflicting feeds blindly;
- compare independent upstreams within explicit price/time tolerances;
- retain every observation;
- emit a canonical/reconciled quote only when policy requirements are met;
- otherwise emit a conflict/degraded result;
- fail closed for execution-sensitive consumers when confidence is insufficient.

Example states:

- CONFIRMED;
- DEGRADED;
- CONFLICTING;
- STALE;
- UNAVAILABLE.

Do not hard-code provider names into reconciliation policy.

## 10. Authority-aware conflict policy

Different fact types require different reconciliation rules.

Examples:

- Exchange trading rules: Tier-0 official source wins.
- Central-bank rate decision: official central-bank document wins.
- Macro release: official/statistical authority or verified vintage source wins.
- Real-time market quote: use independent-feed reconciliation and freshness.
- Breaking geopolitical/news event: radar discovers; official/multiple-source verification raises confidence.

Conflicts must remain queryable; do not silently delete the losing observation.

## 11. PIT / revision semantics

PIT is mandatory for all research-consumable facts.

At minimum preserve:

- `event_time` — when the real-world event/value applies;
- `published_at` / `release_at` — when source published it;
- `observed_at` — when AIC could observe it;
- `ingested_at` — when AIC persisted it;
- `vintage_at` / `revision_at` where the source supports revisions.

Historical queries must not return a document, macro value, revision, speech or filing that was not
available at the requested `as_of`.

Do not substitute today's corrected value for the value available at the historical decision time
unless the caller explicitly requests latest-revised data.

## 12. Persistence

Add PostgreSQL persistence only for the new canonical families.

Requirements:

- immutable raw/source linkage;
- deterministic identities;
- idempotent insertion;
- explicit revision/supersession relationships;
- indexes for source, entity/series/instrument and PIT timestamps;
- no silent overwrite of an earlier observed fact;
- migration upgrade/downgrade;
- in-memory adapter parity where the project convention requires it.

Avoid storing redundant large payloads when an immutable content hash + normalized content and
source identity are sufficient, unless legal/audit requirements need full raw retention.

## 13. Evidence retrieval boundary

Provide application services that can later build an Evidence Pack from canonical data without
knowing concrete providers.

At minimum support queries for:

- latest validated/reconciled market quote;
- historical quote as-of;
- macro series latest / as-of / vintage;
- official documents by institution, speaker, type and time window;
- event candidates by time/category/entity;
- source lineage and quality/conflict evidence.

Do not implement AI investment opinions in this SPEC.

## 14. First implementation checkpoints

### Checkpoint A — Real-time market fabric

- upstream-source lineage;
- EASTMONEY / SINA / TENCENT A-share/ETF/index quote adapters;
- MarketQuote canonical model;
- validation / freshness;
- independent-source reconciliation;
- PostgreSQL persistence + PIT query;
- Provider Runtime health/failover wiring.

### Checkpoint B — Macro vintage fabric

- MacroObservation;
- FRED / ALFRED direct official adapter;
- generic SDMX boundary sufficient for OECD/IMF/BIS without provider-specific domain leakage;
- vintage/revision PIT queries.

### Checkpoint C — Policy/document/event fabric

- SourceDocument;
- official central-bank/policy feed adapters;
- SEC EDGAR and CNINFO document adapters where feasible;
- EventCandidate;
- GDELT radar adapter;
- authority-aware verification states.

### Checkpoint D — Evidence query layer

- unified source-neutral retrieval contract;
- evidence bundle/query DTOs for later Opportunity Radar / Market Regime / Committee consumption;
- no LLM requirement for deterministic tests.

These checkpoints belong to one product SPEC and should not create four governance projects.

## 15. Explicit non-scope

SPEC-011 does not implement:

- Opportunity Radar scoring/stock selection;
- AI Investment Committee opinions;
- autonomous trading;
- Kelly sizing;
- live broker integration;
- leverage;
- high-frequency execution;
- licensed Level-2 / full tick feed unless separately approved;
- social-media sentiment models;
- generalized web scraping platform;
- knowledge-graph inference beyond minimal deterministic entity/source identity;
- political judgments or recommendations.

## 16. Tests

At minimum prove:

1. adapter identity is separate from upstream-source identity;
2. two adapters backed by the same upstream count as one independent source;
3. three independent quote observations can produce CONFIRMED state;
4. one outlier source is retained but does not corrupt the reconciled value;
5. insufficient/contradictory sources fail closed;
6. stale quote detection;
7. Provider Runtime failover does not erase original source attribution;
8. FRED/ALFRED vintage query returns only values available at historical as-of;
9. later macro revision does not leak into earlier historical query;
10. future official document is invisible to earlier as-of;
11. event-radar evidence cannot override an official conflicting fact;
12. duplicate ingestion is idempotent;
13. revision/supersession is append-only;
14. PostgreSQL/in-memory parity where applicable;
15. migrations round-trip;
16. existing PIT, portfolio, execution and SPEC-010 tests do not regress.

Live network tests are optional smoke/integration tests and must not make normal CI depend on third-
party availability. Deterministic fixtures are required for CI.

## 17. Quality gates

Keep the existing engineering gates:

- PostgreSQL tests;
- Ruff;
- strict mypy;
- architecture dependency tests;
- migration round-trip;
- `git diff --check`;
- repository coverage threshold.

Do not add new governance machinery solely for SPEC-011.

## 18. Deliverables

Engineering must deliver:

- source capability matrix;
- selected-provider/upstream rationale;
- new canonical models and ports;
- production adapters for the first approved sources;
- validation/quality/reconciliation policies;
- PostgreSQL migrations and repositories;
- PIT query services;
- deterministic tests;
- concise operating documentation;
- non-blocking technical debt list.

## 19. Source capability matrix format

For each capability record:

- data family;
- capability ID;
- upstream source;
- adapter/project;
- official vs third-party;
- free vs paid;
- asset/geography scope;
- latency/update frequency;
- historical depth;
- PIT/vintage support;
- authority level;
- license / usage constraints;
- health/failover role;
- Primary / Secondary / Radar / Future-Commercial classification.

## 20. Engineering stop condition

Engineering should stop after Checkpoint A–D functionality and exact-HEAD validation are complete.
Do not expand into Opportunity Radar or AI Brain in the same PR/SPEC.

Architecture review should focus on data correctness, PIT, provenance, source independence and
provider replaceability. Non-capital-risk product limitations may be recorded as non-blocking debt.
