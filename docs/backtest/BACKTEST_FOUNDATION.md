# Deterministic Backtest Foundation

## Contract

The daily replay engine consumes scripted order intents; it does not own selection or
strategy logic. Trading sessions and all trade, mark and benchmark prices are queried
through `PointInTimeMarketDataService` using:

```text
HISTORICAL_RESEARCH + explicit aware as_of + RAW
```

Direct historical repositories, latest rows, next-bar substitution and future-complete
data are forbidden. Missing or not-yet-available evidence produces a structured
`MARKET_DATA_UNAVAILABLE` or `PIT_DATA_UNAVAILABLE` error.

## Determinism

Run, policy and source inputs determine order, fill, cash, NAV and audit identities.
There is no random state. Repeating the same run produces equal business evidence.
Replay advances through PIT-visible exchange calendar sessions, never `date + 1` policy.

## V1 execution boundary

- BUY and SELL of existing long positions;
- full fills only at the PIT-visible daily close plus deterministic slippage;
- configurable commission/minimum commission and sell-side stamp tax;
- daily NAV and minimal benchmark/excess-return result;
- no partial fills, leverage, short selling, live broker, formal Strategy Engine or AI.

## Audit chain

The ordered chain is Run Created → Initial Capital → Order → Fill → Cash Change →
Position Change → NAV Snapshot. Stable IDs, timestamps, source IDs, portfolio IDs,
policy versions and immutable payloads make replay evidence comparable.
