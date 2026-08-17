# A-share Instrument Master

`InstrumentMaster` reuses the canonical `InstrumentIdentity` (`market + symbol + type`).
`000001.SZ` maps to `CN.SZSE.000001`; `600000.SH` maps to `CN.SSE.600000`.

V1 stores display name, listing/delisting dates, `LISTED`/`DELISTED`/`UNKNOWN`,
retrieval time and provenance. Listing and delisting dates are inclusive lifecycle
boundaries: dates before listing or after delisting are not expected to have bars.

Tushare `stock_basic` is the V1 adapter source. The official interface returns at most
6000 rows per request, requires 2000 points and permits 50 requests per minute. Sync is
explicit by SSE/SZSE and listing status; reads never trigger a market-wide sync.

Repeated identical facts are `ALREADY_EXISTS`; conflicting facts under the same
canonical identity fail rather than overwrite. V1 stores the current display name and
does not implement full name history, temporal revisions, industries, ST labels,
corporate actions, or a second-provider reconciliation policy.
