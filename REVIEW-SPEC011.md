# Engineering Review — SPEC-011 Global Data Fabric and Event Intelligence Foundation

Review date: 2026-09-21
Repository baseline for Checkpoint B: `origin/main` at `8839eadc0dae5b7be0654531ef49aa76da2ced0e`
Reviewed artifact: `SPEC-011-Global-Data-Fabric-and-Event-Intelligence-Foundation.md`
Source-file SHA-256: `7b4d788cede5863be20197da2072e714fa7f1164b443e69d9b6c096bd4ccbc8b`
Imported-file SHA-256: `fba814629eeb1c947dc82ea937f1ee0b46a72e2d033d7246abb1a1631ffd4581`
Import normalization: trailing Markdown whitespace and the extra final blank line were removed;
the specification text and requirements are unchanged.
Decision: **APPROVED FOR REPOSITORY IMPORT AND IMPLEMENTATION PLANNING**
Development status: **CHECKPOINT B IMPLEMENTED — validation and independent Architecture Review pending**

## Checkpoint B implementation review

Checkpoint B adds source-neutral macro vintage, scheduled-event and continuous-acquisition
foundations while preserving the existing Provider Runtime and PIT architecture:

```text
MacroAcquisitionService (cadence/checkpoint owner)
  -> existing ProviderRuntimePort (selection/health/failover owner)
  -> official FRED/ALFRED adapter
  -> existing immutable RawObservation + SourceLineage
  -> MacroNormalizer
  -> immutable MacroSeriesIdentity / MacroObservation repository
  -> existing DataAvailabilityPolicy
```

`MacroSeriesIdentity` binds series, unit, frequency, seasonal adjustment, geography and the factual
source agency. `SourceLineage.upstream_source_id=FRED_ALFRED` separately identifies the transport
and historical-version platform. A BLS or BEA fact obtained directly and through FRED remains one
underlying agency fact for independence purposes. Query modes are explicit:
`KNOWN_AT(as_of)`, `AS_PUBLISHED(vintage_date)` and `LATEST_REVISED`. Revision values append with a
deterministic predecessor link; a later revision never replaces an earlier value.

`ScheduledEvent` appends publication, reschedule, cancellation and completion versions. Research
queries select the version published by the requested time; operational replay selects the version
actually ingested by that time. Completion requires immutable links to the actual raw observation,
macro vintage or later document evidence.

Acquisition plans hold normal and release-window cadence, bounded overlap, cursor, watermark,
last-success and retry state. PostgreSQL claims lock the checkpoint row and issue a monotonically
increasing fencing token. Evidence is persisted before cursor advancement. Failed persistence
releases the lease but retains the old cursor/watermark, and restart resumes through the same
deterministic raw and canonical identities. Provider health, selection and failover remain owned by
the existing Runtime.

The direct FRED/ALFRED adapter uses only official REST endpoints and the existing `httpx`
dependency. It requires an API key when enabled, applies explicit timeout and payload bounds,
sanitizes errors and never records the key in source URIs. ALFRED revision intervals are requested
explicitly. FRED is the transport; the series producer remains separately attributed. BLS, BEA and
Federal Reserve calendar adapters remain subsequent bounded source integrations over the delivered
source-neutral `ScheduledEvent` contract; Checkpoint B does not introduce a broad crawler or any
Checkpoint C behavior.

Migration `20260921_0017` creates macro series/observations, scheduled-event versions, acquisition
plans and fenced checkpoints. Downgrade removes this evidence and progress state, so a production
downgrade is destructive and requires stopped workers, backup and separate operational approval.

### Checkpoint B requirement-to-test traceability

| Requirement | Deterministic evidence |
| --- | --- |
| Latest versus historical vintage, revision chain and source-agency identity | `test_spec011_macro_calendar.py`; `test_evidence_postgresql.py` |
| Publication/vintage/as-of boundary and future-vintage rejection | `test_spec011_macro_calendar.py` |
| Schedule reschedule, cancellation and actual-release linkage | `test_spec011_macro_calendar.py`; `test_evidence_postgresql.py` |
| Official FRED/ALFRED contract, bounded credentials and revision request | `test_fred_provider.py` |
| Release-window cadence and bounded-overlap cursor | `test_macro_acquisition.py` |
| Persistence-before-cursor, failure recovery and idempotent restart | `test_macro_acquisition.py`; `test_evidence_postgresql.py` |
| Multi-worker lease/fencing and PostgreSQL/in-memory parity | `test_macro_acquisition.py`; `test_evidence_postgresql.py` |
| Clean Architecture and reuse of Provider Runtime | repository architecture tests |

## Checkpoint A implementation review

Checkpoint A extends the reviewed architecture without creating a second provider registry,
failover engine, PIT engine, canonical path or quality framework. The delivered path is:

```text
RealtimeMarketQuoteService
  -> existing ProviderRuntimePort
  -> disabled-by-default domestic quote adapter
  -> immutable RawObservation + SourceLineage
  -> MarketQuote normalizer / existing validation and quality contracts
  -> PostgreSQL raw, quote and reconciliation repositories
  -> existing DataAvailabilityPolicy
```

The implementation adds `SourceLineage` with separate adapter and real upstream identities,
authority/source classification, event/publication/observation/ingestion timestamps, raw hash,
transformation version, stable source locators and optional license identity. Reconciliation
collapses observations by `upstream_source_id`: AKShare(Eastmoney), efinance(Eastmoney), a transport
fallback or another AIC adapter over Eastmoney remains one vote. Confirmed confidence requires at
least two fresh independent upstreams with compatible prices and session state. Missing quorum,
stale evidence and conflicts remain explicit degraded, unavailable or conflicted results.

`MarketQuote` uses the existing canonical `InstrumentIdentity`. Equity must exist in Instrument
Master, ETF in the existing ETF profile repository and index quotes in the existing non-tradable
`IndexReference` namespace. Unknown identities fail before Provider Runtime invocation. Index source
codes preserve their exchange suffix while the canonical identity remains `REFERENCE.INDEX`; no
reference series can enter the execution model.

The global Market Pulse foundation covers equity index, sovereign yield, FX, gold, crude oil and
volatility families through `MarketSeriesIdentity` and immutable `MarketPulseObservation`.
Checkpoint A deliberately adds no licensed realtime benchmark adapter. Daily, delayed and realtime
publication modes are distinct, and execution imports neither pulse identity nor observations.

Migration `20260921_0016` creates immutable raw observations, canonical source quotes,
reconciliation decisions and market-pulse observations. Inserts use deterministic identity with
insert-or-verify conflicts. Downgrade removes all four tables and their audit evidence, so it is
destructive and requires backup plus explicit operational authorization outside isolated tests.

### Source and license gate

The source review was refreshed on 2026-09-21. No stable official developer contract granting AIC
commercial machine access to the Eastmoney `push2`, Sina `hq.sinajs.cn` or Tencent `qt.gtimg.cn`
quote endpoints was found. The [Sina Finance user agreement](https://finance.sina.com.cn/roll/2021-05-12/doc-ikmxzfmm2033220.shtml)
requires written permission for relevant captured data and prohibits commercial use beyond the
written permission scope. Tencent's [corporate terms](https://www.tencent.com/term-of-service/)
defer product use to the product-specific agreement and do not establish quote API rights. The
documented Eastmoney EMT/Quant products are separate licensed products and do not authorize the
public `push2` endpoint by implication.

Accordingly, all three builders reject an enabled configuration unless
`upstream_access_authorized=true` is explicitly recorded. Required tests use owned deterministic
fixtures and never contact those endpoints. AKShare, efinance and easyquotation remain protocol
references only; none is a runtime dependency or an independent authority.

### Requirement-to-test traceability

| Checkpoint A requirement | Deterministic evidence |
| --- | --- |
| Lineage, immutable raw evidence and PIT/no-lookahead | `test_spec011_market_quotes.py`; `test_market_intelligence_postgresql.py` |
| Equity/ETF/index-reference identity fail closed | `test_realtime_market_quotes.py`; `test_domestic_quote_providers.py` |
| Three upstream adapter contracts and production authorization gate | `test_domestic_quote_providers.py` |
| Independent-source, stale and conflict reconciliation | `test_spec011_market_quotes.py` |
| Adapter/library aliases and failover cannot fabricate consensus | `test_realtime_market_quotes.py` |
| PostgreSQL restart/idempotency and reversible migration | `test_market_intelligence_postgresql.py` |
| Global pulse identity/PIT and execution isolation | `test_spec011_market_quotes.py`; repository architecture tests |

Checkpoint A does not implement the Checkpoint B macro/vintage providers, Checkpoint C
ScheduledEvent/document/event intelligence, Checkpoint D Evidence Pack, or the later durable cadence
and lease scheduler. The application quote coordinator invokes the existing Provider Runtime for
the bounded Checkpoint A acquisition path; continuous plan/cursor scheduling remains a later frozen
checkpoint deliverable.

## Review result

SPEC-011 has no inherent architecture conflict with AIC. Its product direction is compatible with
the existing Provider Runtime, Data Foundation, PIT policy, quality model and PostgreSQL adapters.
The implementation must extend those components rather than reproduce them. In particular:

1. Provider discovery, registration, health, scoring, selection, invocation and bounded failover
   remain owned by the existing Provider Runtime.
2. New data families enter through `RawObservation`, source-neutral normalization, validation,
   quality assessment and canonical persistence. They do not create a second canonical path.
3. Historical queries use the existing `DataAvailabilityPolicy` and
   `PointInTimeMarketDataService`; each new family adds explicit availability semantics to that
   policy rather than implementing an independent PIT engine.
4. Multi-source reconciliation is an application service over observations obtained through the
   Provider Runtime. It is not a replacement registry or failover engine. Provider failover selects
   a usable provider for one request; reconciliation deliberately gathers multiple independent
   upstream observations and records the decision.
5. `adapter_id` identifies the AIC adapter. `upstream_source_id` identifies the publisher/feed that
   originated the fact. Independence, confidence and voting are keyed by upstream identity, never
   by Python package or adapter count.
6. Continuous acquisition is an application-owned scheduler that submits capability requests to the
   existing Provider Runtime. Provider selection, health, cooldown, retryability and failover remain
   Runtime responsibilities; acquisition cadence, cursors and durable progress do not form a second
   Provider Runtime.
7. The global market pulse uses reference-only cross-asset series for global equity indexes,
   sovereign yields, FX, gold, crude oil and volatility. These facts inform risk transmission but do
   not make a benchmark or reference series executable.
8. A source-neutral `ScheduledEvent` stores the schedule known at each point in time. Reschedules and
   cancellations append versions, and the scheduled record is later linked to the actual release,
   observation or document without rewriting either item.
9. Official evidence extends beyond central banks to fiscal, trade, sanctions, regulators,
   statistics, energy, international institutions, exchange disclosures and issuer IR/management
   statements under the same authority, provenance and PIT rules.

The specification is therefore safe to import unchanged. The engineering questions below constrain
implementation choices without changing the product requirements.

## Existing capability mapping

| Area | Existing AIC implementation to reuse | Engineering implication / gap |
| --- | --- | --- |
| Provider Runtime | `provider_runtime` registry, lifecycle, health, scoring, selector, invocation, bounded failover and runtime composition | Register the new capability IDs and adapters here. Add lineage inputs to results; do not add another provider registry or failover loop. |
| Raw observations | `RawObservation`, deterministic raw payload hashing and source metadata in `domain/market_data/models.py` | Generalize the ingestion boundary beyond `DailyBar`; add a typed source-lineage value object for new families. Persist immutable observation evidence. |
| Canonical data | `CanonicalRecord`, `DailyBar`, deterministic record identity and the normalizer/validator/quality ingestion sequence | Keep family-specific canonical models. Do not force quotes, macro data or documents into `DailyBar`. |
| Validation | Validation protocols and canonical validation service | Extend dispatch with family validators and fail-closed identity, units, timestamps and value checks. Avoid a second validation framework. |
| Quality | Quality assessment, freshness/conflict flags and provider quality scoring | Add family policies and upstream-aware conflict evidence. Provider health score remains operational selection evidence, not factual consensus. |
| PIT / no-lookahead | `DataAvailabilityPolicy`, `PointInTimeMarketDataService`, historical-research and operational-replay contexts | Add quote, macro-vintage, document and event availability rules. A historical query may only see evidence both published/released and observed by its `as_of`. |
| PostgreSQL | Canonical daily-bar and specialized trading-calendar, instrument, corporate-action, ETF/index repositories with in-memory parity | Add reversible migrations and repositories for the new families. Reuse transaction, conflict and identity conventions. No production schema change is part of this planning checkpoint. |
| Tushare | Real HTTPS adapter, explicit capabilities, error mapping, timeouts and production builder | Preserve it for historical/daily/reference use and reuse its adapter structure. It is not an independent real-time confirmation of Eastmoney/Sina/Tencent. |
| Instrument master | `InstrumentIdentity`, A-share instrument master and PIT trading status | Extend supported identity coverage only as required for domestic Equity, ETF and index references. Quote ingestion must resolve a known canonical identity or fail closed. |
| ETF / index | ETF profile, ETF-index relationship, index reference, execution profile and corresponding persistence | Reuse the same identities and tradability boundary. An index quote remains reference evidence and never becomes executable merely because it is fresh. |
| Failover / health / scoring | Health monitor, cooldown, capacity, deterministic selection, quality score and retryable failure policy | Use these for transport/provider availability. Store reconciliation confidence separately from provider operational health. |
| Historical backfill / coverage | `BackfillAttempt`, coverage repositories, interval gap calculation and deterministic idempotent ingestion | Generalize the attempt/checkpoint concepts for capability scopes and provider cursors; preserve the existing family-specific backfill behavior. |
| Runtime operational state | Provider metrics including `last_success_at`, `last_failure_at`, freshness, capacity and cooldown | Reuse these signals in cadence decisions. Persist acquisition progress separately because provider health is not a source cursor or completion watermark. |

## Required architecture shape

The data path for every new family is:

```text
application acquisition coordinator (cadence + durable checkpoint)
  -> existing Provider Runtime invocation/health/selection/failover
  -> provider adapter
  -> immutable RawObservation + SourceLineage
  -> family normalizer
  -> existing validation and quality contracts
  -> family canonical record
  -> PostgreSQL repository
  -> existing PIT policy/query service
  -> Evidence Query application service
```

For independently corroborated market data, a coordinator asks the Provider Runtime for a bounded
set of configured upstreams, deduplicates results by `upstream_source_id`, and passes them to a
deterministic reconciler. It stores every accepted raw observation plus the reconciliation decision.
A failed or stale source lowers coverage/confidence; it does not silently become agreement.

Clean Architecture ownership remains unchanged:

- Domain owns source-neutral identity, lineage, canonical facts and reconciliation rules.
- Application owns ports, orchestration, PIT-safe queries and Evidence Pack assembly.
- Provider adapters own source protocol and field parsing.
- Infrastructure owns PostgreSQL storage and migrations.
- Bootstrap remains the composition root for production adapter registration.

## Gaps to implement

1. A common lineage model containing `adapter_id`, `upstream_source_id`, `authority_level`,
   `source_type`, `event_time`, `published_at`, `observed_at`, `ingested_at`, `raw_hash` and
   `transformation_version` does not yet exist.
2. `ProviderAttribution` identifies a provider but not the distinct upstream authority. Existing
   quality conflicts are likewise provider-keyed rather than upstream-keyed.
3. The current ingestion service and concrete quality implementation are centered on `DailyBar`.
4. Raw observations are modeled but lack a general immutable PostgreSQL evidence repository.
5. Realtime quote, macro series/vintage, official document and event-candidate domain families are
   absent.
6. There is no deterministic independent-source reconciliation record or confidence policy.
7. PIT record dispatch does not yet include the new families or macro revision/vintage semantics.
8. No production adapters exist for Eastmoney, Sina, Tencent, FRED/ALFRED, SDMX institutions,
   official document feeds, SEC EDGAR, CNINFO or GDELT.
9. Evidence Pack/query contracts for downstream regime, research, radar and committee consumers are
   absent.
10. There is no source-neutral reference model for global equity indexes, sovereign yields, FX,
    commodities or volatility indicators, and existing `InstrumentIdentity` should not be stretched
    into a second executable-asset model for non-tradable benchmarks.
11. There is no durable continuous-acquisition plan/checkpoint contract covering cadence, cursors,
    watermarks, leases, catch-up and rate-limit-aware recovery.
12. Economic, policy and issuer calendars lack a source-neutral `ScheduledEvent` with append-only
    schedule revisions and links to actual released evidence.
13. The official-source roadmap needs adapters/classification for fiscal, trade, sanctions,
    regulators, statistics, energy, international organizations and issuer IR sources.

## Engineering questions and assumptions

These questions are recorded for the implementation review. They do not modify the business goal.

1. `market.quote.realtime` is treated as a capability name, not a promise that V1 uses a persistent
   stream. Polling snapshots may implement it initially when the upstream only exposes request/response.
   True streaming can use the existing capability mode when a supported source is selected.
2. The existing `DataCapability` vocabulary and Provider Runtime capability IDs need one explicit
   mapping. They must not evolve into competing registries.
3. Source-specific freshness windows, cross-source price/volume tolerances and minimum confidence
   are configuration owned by the application and approved per asset/session. Until approved,
   capital-affecting consumers fail closed on unknown or conflicting data.
4. A macro fact is historically available only when its release/publication timestamp and AIC
   observation timestamp are both within `as_of`. A date-only official release uses a documented,
   conservative availability boundary; it is never backfilled to midnight without evidence.
5. ALFRED revisions are stored as distinct immutable vintages. “Latest” and “known at time” are
   different explicit queries.
6. Document supersession is asserted only when the publisher supplies an identity/version link or
   when exact deterministic rules prove it. Title similarity alone cannot rewrite history.
7. Entity resolution starts with official identifiers and reviewed aliases. Probabilistic matches
   remain candidates and cannot overwrite canonical identity.
8. CNINFO is authoritative for disclosures, but a stable documented public machine API and its
   production usage terms still require verification. Until then, use permitted official pages/files
   with conditional retrieval and fail closed; do not depend on an undocumented reverse-engineered API.
9. Eastmoney, Sina and Tencent public quote endpoints need legal/terms and operational validation
   before production activation. Open-source code is useful for protocol discovery, not permission
   or source authority.
10. Two libraries reading Eastmoney count as one upstream observation. A proxy or cache does not
    create an independent source either.
11. GDELT can create `RADAR` candidates only. Policy/fact promotion requires Tier-0 verification or
    an explicitly approved corroboration rule.
12. Raw payload retention, compression, redaction and license constraints require an operational
    retention decision before migration approval. At minimum, the immutable hash, lineage and
    transformation identity must survive.
13. Global index, gold, crude and volatility benchmarks may be visible on public websites while
    programmatic or redistributable realtime use remains licensed. AIC must record the license/SLA
    basis and must not scrape a page whose terms prohibit automated extraction.
14. A global pulse value is reference evidence. It cannot become an orderable instrument without a
    separately approved instrument-master, market, currency, trading-status and execution mapping.
15. Acquisition jobs use a PostgreSQL lease/fencing token for multi-worker ownership and advance a
    cursor/watermark only after durable evidence persistence. Provider Runtime health/cooldown stays
    authoritative for provider availability.
16. When a feed has no resumable cursor, catch-up uses a bounded overlap window plus deterministic
    identities. Duplicate observations are idempotent; late corrections append new versions.
17. A scheduled event's first publication, later time changes, cancellation and completion are
    separate immutable versions. Historical queries return the schedule known at `as_of`, not the
    current calendar retroactively.
18. Earnings schedules use issuer IR or official exchange disclosures as Tier 0 where available.
    Aggregator calendars remain Tier 1 discovery until confirmed, and the actual filing/document is
    linked after release.

## Dependency and source conclusion

No new runtime dependency is required for the first quote adapter prototypes: the repository already
uses an owned HTTP boundary and `httpx`. Direct adapters keep timeout, retry, lineage and error
semantics under AIC control. AKShare, efinance, easyquotation and adata are valuable implementation
references, but they must not be treated as authorities or as four independent sources.

FRED/ALFRED and simple REST/JSON or SDMX-CSV endpoints can also begin with the owned HTTP boundary.
An SDMX client should be added only if it materially reduces standards risk after license,
maintenance and transitive-dependency review. For XML/RSS, prefer JSON/CSV where the official source
supports it; otherwise select a hardened parser after a separate dependency review.

SEC EDGAR should use the official `data.sec.gov` contract and required declared User-Agent. Third-
party EDGAR libraries are references or optional accelerators, not the authority. GDELT client
libraries reviewed so far do not justify a runtime dependency; the official feeds/APIs are simple
enough for an owned adapter.

Official daily/statistical sources can seed sovereign yields, FX and energy indicators, while
realtime global index, commodity benchmark and volatility feeds may require exchange/index-owner
licenses. Free publication access is not treated as programmatic redistribution permission. The
roadmap therefore supports delayed/daily official evidence first and keeps licensed realtime
enhancement behind an explicit source and contract review.

## Scope decision

This checkpoint imports the unmodified specification and records review/planning evidence only. It
does not add provider capabilities, application ports, product code, dependencies, migrations,
production configuration, governance events or SPEC-011 engineering state. Implementation remains
blocked on SPEC-010 closeout and explicit development authorization.
