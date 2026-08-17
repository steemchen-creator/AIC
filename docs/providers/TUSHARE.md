# Tushare Pro Daily Provider

## Contract

- Provider ID: `tushare_pro` (the Runtime ID grammar does not permit hyphens).
- Implementation: `providers.tushare_daily`, explicitly allowlisted by Bootstrap.
- Capability: `market.daily.read` version `1.0.0`, batch mode.
- Scope: A-share daily bars for `.SZ` and `.SH` only.
- Credential: `AIC_TUSHARE_TOKEN`, environment-only and excluded from payloads,
  provenance, logs, errors, fixtures, and source URIs.

The adapter calls Tushare's official HTTPS endpoint through `httpx`. This avoids the
SDK's broader pandas dependency and keeps timeout and error conversion explicit.

## Schema and units

RawObservation retains `ts_code`, `trade_date`, OHLC, `vol`, and `amount`. Tushare
`vol` is lots (手), converted to canonical shares by exactly ×100. Tushare `amount`
is thousand CNY, converted to canonical yuan by exactly ×1000. Decimal conversion
uses strings; NaN, infinity, missing values, unsupported exchanges, and malformed
dates fail without repair.

`trade_date` becomes 15:00 Asia/Shanghai (07:00 UTC), the daily period end rather
than a precise trade timestamp. Transformation version is `tushare-daily-bar/v1`;
source URIs use `tushare://daily/<ts_code>`.

## Operations and limitations

Calls have explicit timeouts. Authentication, permission, rate limit, timeout,
network, malformed-response, empty-result, and invalid-request cases remain distinct.
Health is a lightweight initialized/configuration check and consumes no data quota.
There is no retry engine or scheduler. Required tests use deterministic fixtures;
optional live smoke needs an explicit local token and is not a CI gate.

Phase 7 historical backfill supplies canonical `symbol`, `market`, `start_date` and
`end_date` values. Translation to Tushare `.SH`/`.SZ` codes and compact dates occurs
only inside this adapter. Historical query itself is PostgreSQL-only and cannot consume
network quota. Completed empty Provider responses are valid coverage evidence.

Phase 8 adds the separate `market.calendar.read` capability using `trade_cal`. The
adapter returns only Provider fields (`exchange`, `cal_date`, `is_open`); standard A-share
session times are owned by the source-neutral Session Policy, not attributed to Tushare.

This Provider does not support real-time/minute/L2 data, financials, news, funds,
institutional holdings, strategies, AI, trading, portfolios, reconciliation, or a
second real Provider.
