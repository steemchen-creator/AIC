# Instrument Trading Status

`InstrumentTradingStatus` is a date-specific security fact, separate from the slower
changing Instrument Master and from exchange-level Trading Calendar facts. States are
`TRADING`, `SUSPENDED`, and `UNKNOWN`.

Tushare `suspend_d` is the V1 source. Official rows are suspension (`S`) or resumption
(`R`) events with `ts_code`, `trade_date`, optional intraday timing and event type.
`S` maps to `SUSPENDED`; `R` proves `TRADING` only on that resumption date. An empty
response establishes operational query coverage but never invents a `TRADING` fact.

Backfill is explicit, bounded, sequential, idempotent and resumable. Only completed
request intervals establish coverage. Partial/failed attempts remain audit evidence.

Historical gap classification uses evidence in this order: complete Calendar coverage,
exchange OPEN, listing lifecycle, complete status coverage, explicit status, then bar
presence. It returns market-closed/not-listed/delisted/suspended, probable data gap, or
unknown. `PROBABLE_DATA_GAP` is a data-integrity result, never a trading signal.

V1 does not model minute-level temporary suspensions, infer continuing suspension
between events, or implement corporate actions and temporal status revisions.
# Point-in-time status

停复牌事实只有在其 availability evidence 不晚于 `as_of` 时才可见。后来补录的状态不能
用于 Operational Replay 的过去时点；缺失 provider timestamp 的 Historical Research
状态保持 Unknown，而不是默认正常交易。
