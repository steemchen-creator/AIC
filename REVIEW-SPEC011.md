# Engineering Review — SPEC-011 Global Data Fabric and Event Intelligence Foundation

Review date: 2026-09-21
Repository baseline: `origin/main` at `690f4740e33643ae89b543447f3f7619791c1e77`
Reviewed artifact: `SPEC-011-Global-Data-Fabric-and-Event-Intelligence-Foundation.md`
Source-file SHA-256: `7b4d788cede5863be20197da2072e714fa7f1164b443e69d9b6c096bd4ccbc8b`
Imported-file SHA-256: `fba814629eeb1c947dc82ea937f1ee0b46a72e2d033d7246abb1a1631ffd4581`
Import normalization: trailing Markdown whitespace and the extra final blank line were removed;
the specification text and requirements are unchanged.
Decision: **APPROVED FOR REPOSITORY IMPORT AND IMPLEMENTATION PLANNING**
Development status: **NOT AUTHORIZED — wait for SPEC-010 formal closeout and an explicit start instruction**

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
