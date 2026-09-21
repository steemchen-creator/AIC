# FRED/ALFRED Official Provider

## Contract

- Provider ID: `fred_official`.
- Implementation: `providers.fred_official`, explicitly allowlisted by Bootstrap.
- Capabilities: `macro.series.read`, `macro.release.read` and `macro.vintage.read`.
- Credential: `AIC_FRED_API_KEY`, injected by the deployment secret store and excluded from
  payloads, logs, errors, provenance and source URIs.

The adapter calls the official FRED/ALFRED HTTPS API directly through the existing Provider
Runtime. It has explicit timeouts and a 2 MB response limit. Ordinary tests use deterministic owned
fixtures and never contact the service. An enabled provider without a key fails closed during
initialization; the adapter is otherwise safe to leave disabled.

## Identity and PIT semantics

FRED/ALFRED is the transport and vintage-history upstream. It is not automatically the producer of
the underlying fact. Each `MacroSeriesIdentity` stores the actual source agency, such as BLS or BEA,
separately from `SourceLineage.upstream_source_id=FRED_ALFRED`. Fetching a BLS series through both
FRED and a direct BLS adapter therefore does not create two independent factual authorities.

Vintage acquisition requests explicit real-time intervals and revision output. The canonical model
preserves release date, real-time start/end, vintage identity, first observation and ingestion time.
Date-only releases use end-of-day UTC as a conservative availability boundary. Consumers must
choose `KNOWN_AT`, `AS_PUBLISHED` or `LATEST_REVISED`; historical research cannot silently use the
latest revised value.

## Scheduling and failure behavior

Application-owned acquisition plans decide normal and release-window cadence and then invoke the
existing Provider Runtime. The adapter does not implement another registry, selector, retry loop or
failover engine. Rate limits and transport failures keep the prior durable cursor/watermark; the
acquisition checkpoint records a bounded retry time. Cursor advancement occurs only after immutable
raw and canonical evidence persistence succeeds.
