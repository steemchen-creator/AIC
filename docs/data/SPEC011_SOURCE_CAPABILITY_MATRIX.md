# SPEC-011 Source, Capability and Dependency Roadmap

Status: planning evidence only
Review date: 2026-09-21

## Source matrix

`adapter_id` values below are proposed AIC identities. `upstream_source_id` is the factual origin and
the only identity used to count independent confirmations.

| Family / capability | Proposed `adapter_id` | `upstream_source_id` | Authority / type | Access and cost | PIT / reconciliation role | Engineering disposition |
| --- | --- | --- | --- | --- | --- | --- |
| A-share/ETF/index quote | `eastmoney.quote.http.v1` | `EASTMONEY` | Tier 1 / public market feed | Free public web endpoint; no stable official developer contract found | Independent quote observation | Direct bounded HTTP adapter after terms and endpoint validation; fixtures/canary required |
| A-share/ETF/index quote | `sina.quote.http.v1` | `SINA` | Tier 1 / public market feed | Free public web endpoint; no stable official developer contract found | Independent quote observation | Same controls; explicitly distinct from Eastmoney |
| A-share/ETF/index quote | `tencent.quote.http.v1` | `TENCENT` | Tier 1 / public market feed | Free public web endpoint; no stable official developer contract found | Independent quote observation | Same controls; encoding/schema drift fixtures required |
| Daily/reference data | existing Tushare adapter | `TUSHARE` | Tier 3 / commercial-enhanced API | Existing token and plan constraints | Historical/reference; not realtime quorum by default | Preserve current production adapter and capability boundaries |
| US macro / vintages | `fred.api.v1` | `FRED_ALFRED` | Tier 0 / official API | Official API; free key required | `release_at`, realtime period and vintage identity | First macro adapter; direct official REST |
| OECD macro | `oecd.sdmx.v1` | `OECD` | Tier 0 / official SDMX API | Public/free, documented rate limits | Official series/release observations | Shared SDMX transport, OECD-owned dataset mapping |
| IMF macro | `imf.sdmx.v1` | `IMF` | Tier 0 / official SDMX API | Official SDMX; current portal/auth details require validation | Official series/release observations | Contract spike before production; fail closed on access/schema uncertainty |
| BIS macro | `bis.sdmx.v1` | `BIS` | Tier 0 / official SDMX API | Public/free, documented SDMX endpoints | Official rates/credit/liquidity series | Direct official endpoint; preserve terms/attribution |
| ECB data | `ecb.data_api.v1` | `ECB` | Tier 0 / official SDMX API | Public/free | Rates/FX/monetary observations | Optional first-wave macro complement |
| Fed policy | `fed.official_feed.v1` | `FEDERAL_RESERVE` | Tier 0 / official feed/document | Public RSS/HTML | Publication and document version evidence | RSS discovery followed by official document retrieval |
| ECB policy | `ecb.official_feed.v1` | `ECB` | Tier 0 / official feed/document | Public RSS/MID/HTML | Publication and document version evidence | Prefer structured official feeds and canonical pages |
| BOJ policy | `boj.official_feed.v1` | `BOJ` | Tier 0 / official feed/document | Public official pages/RSS where offered | Publication and document version evidence | Feed/page adapter with hash and conditional retrieval |
| PBOC policy | `pboc.official_page.v1` | `PBOC` | Tier 0 / official document | Public official pages/PDF; stable machine feed not yet established | Publication and document evidence | Conservative page/PDF retrieval; endpoint stability is an implementation gate |
| US filings | `sec.edgar.v1` | `SEC_EDGAR` | Tier 0 / official API/files | Public/free; declared User-Agent and fair-access limits | Accession/filing/XBRL PIT evidence | Direct `data.sec.gov` first; nightly bulk for backfill where appropriate |
| China disclosures | `cninfo.disclosure.v1` | `CNINFO` | Tier 0 / official disclosure platform | Official public pages/files; documented machine-access terms need validation | Announcement/document PIT evidence | Do not depend on undocumented reversed endpoints; identity must bind issuer/security |
| Event discovery | `gdelt.events.v2` | `GDELT` | Tier 2 / radar feed | Public/free | Candidate discovery only | Cannot promote/overwrite Tier-0 fact; official verification link required |

## Global Cross-Asset Market Pulse capability universe

These capabilities belong to the SPEC-011 roadmap but are not all Checkpoint A commitments. Daily,
delayed and realtime values are different products with different freshness and license metadata.
Public display access never authorizes automated extraction or redistribution.

| Pulse family / capabilities | Benchmark universe | Preferred upstream authority | Initial delivery and constraints |
| --- | --- | --- | --- |
| Global equity indexes — `market.index.snapshot`, `market.index.read` | S&P 500, Nasdaq-100, DJIA, STOXX Europe 600, FTSE 100, DAX, Nikkei 225, TOPIX, Hang Seng, CSI 300/SSE Composite and approved regional indexes | Index owner/exchange: S&P DJI, Nasdaq, STOXX/Deutsche Börse, FTSE Russell, JPX/Nikkei, Hang Seng Indexes/HKEX, CSI/SSE/SZSE | Register reference-series identities in A. Select delayed/daily or licensed realtime adapter per benchmark; never infer authority from a portal that republishes the index. |
| Sovereign yields — `market.yield.snapshot`, `market.yield.read` | Policy-relevant tenors for US, euro area/Germany, UK, Japan and China | US Treasury/Federal Reserve, ECB/national debt offices, BoE, BOJ/MOF Japan, PBOC/ChinaBond or approved official source, BIS/OECD | B starts with official daily/reference curves. Intraday rates require an approved licensed market feed. Preserve tenor, curve methodology and publication time. |
| FX — `market.fx.snapshot`, `market.fx.read` | USD/CNY, EUR/USD, USD/JPY, GBP/USD, an approved trade-weighted USD series and other policy-relevant crosses | ECB reference rates, Federal Reserve H.10, PBOC/SAFE and other issuing central banks; licensed market feed for realtime | B supplies official reference/PIT series. A extension may add market snapshots; reference rates and executable FX quotes are never interchangeable. |
| Gold — `market.commodity.snapshot`, `market.commodity.read` | LBMA gold benchmark plus an explicitly named licensed market proxy where required | LBMA/benchmark administrator; licensed exchange/vendor for realtime | Historical/daily first after usage-right review. Realtime is commercial/licensed unless a compliant official contract is identified. |
| Crude oil — `market.commodity.snapshot`, `market.commodity.read` | WTI and Brent spot/benchmark, inventories and approved futures reference | EIA for official spot/inventory series; CME/NYMEX and ICE for licensed exchange data | B uses EIA daily/weekly evidence. Realtime futures/benchmark delivery waits for an approved market-data license. |
| Volatility — `market.volatility.snapshot`, `market.volatility.read` | Cboe VIX plus approved regional, rates, oil and gold volatility benchmarks | Cboe/index owner; licensed market-data feed where required | Official historical files or licensed feed only. Cboe delayed quote pages that prohibit automated extraction must not be scraped. |

Pulse records are reference evidence. Each identity includes benchmark owner, exact methodology/
series, geography, currency or unit, tenor/contract where applicable and publication/freshness mode.
Different benchmark definitions may be shown together but cannot be reconciled as independent votes
for one fact.

## ScheduledEvent / Economic and Policy Calendar roadmap

| Scheduled-event family / capabilities | Primary sources | PIT and actual-event linkage |
| --- | --- | --- |
| Central-bank meetings and decisions — `calendar.event.read`, `calendar.event.changes` | Fed/FOMC, ECB Governing Council, BOJ, PBOC and other official bank calendars | Append initial schedule, reschedules and cancellations. Link the completed event to the official decision, minutes and statement documents. |
| Macro/statistical releases — `calendar.event.read`, `macro.release.read` | BLS, BEA, Census, Eurostat, NBS China, national statistics offices, FRED release metadata | Preserve source timezone and release window. Link to the released `MacroObservation` vintage and official release document. FRED release dates supplement rather than override the originating agency calendar. |
| Fiscal/debt/trade/energy events — `calendar.event.read` | Finance ministries/treasuries, debt offices, customs/trade authorities, EIA/IEA/OPEC and official auction/release calendars | Preserve calendar version and subject definition; link to the actual auction, budget, trade or energy release. |
| Earnings and issuer events — `calendar.event.read`, `official.issuer.read` | Verified issuer IR calendars, official exchange disclosure services and filings | Issuer-confirmed schedule is Tier 0. Aggregators remain discovery. Link to the actual results filing, presentation, management statement or cancellation. |
| Investment-relevant official events | Regulators, legislatures, sanctions authorities, international institutions and verified official calendars | Store deterministic scope and authority. Do not infer an exact event time from media speculation. Link to the resulting official action/document when published. |

A `ScheduledEvent` contains a stable event identity, event type, subject/entity/series/geography,
scheduled time or window, timezone, status, schedule-version/predecessor identity, source lineage and
zero or more immutable actual-evidence links. `scheduled_for` is not an availability timestamp;
historical visibility depends on when that schedule version was published and observed.

## Acquisition cadence roadmap

| Source/capability class | Cadence policy | Cursor/watermark and recovery |
| --- | --- | --- |
| Domestic realtime quotes | Market-session-aware fixed polling, bounded by source quota and freshness target | Watermark by source timestamp plus bounded overlap; deterministic IDs absorb duplicates; provider cooldown/rate limit delays the next due run |
| Global pulse snapshots | Source publication cadence or approved market-session polling; daily sources are never labeled realtime | Series/upstream timestamp watermark; backfill official gaps without substituting a different benchmark definition |
| Macro and vintages | Normal low-frequency poll plus release-window polling from `ScheduledEvent` | Release/vintage cursor where offered; otherwise period/vintage watermark and overlap; revisions append |
| Official feeds, filings and documents | Conditional feed/page polling using upstream cursor, ETag/Last-Modified or stable document ID | Commit cursor only after evidence persistence; reconnect from cursor or overlap; unchanged content hash is idempotent |
| Calendars | Periodic horizon refresh plus targeted refresh near scheduled time | Append changed schedule versions; preserve last successful horizon coverage and backfill missed revisions |
| GDELT/radar | Bounded incremental windows at the documented publication cadence | Resume from last complete window; gaps create catch-up work and never promote partial radar evidence to Tier 0 |

All jobs are application-owned plans invoking the existing Provider Runtime. Runtime health,
selection, concurrency, cooldown and failover remain authoritative; the acquisition checkpoint stores
only plan progress, durable last success, source cursor/watermark, lease/fencing and recovery state.

## Broadened official policy, people and geopolitical source universe

| Theme | Source universe | Capability roadmap | Authority notes |
| --- | --- | --- | --- |
| Monetary and financial stability | Fed, ECB, BOJ, PBOC, BoE, BIS and other official central banks/supervisors | `official.document.read`, `official.feed.read`, `calendar.event.read` | Decisions, minutes, speeches, testimony, stability reports and regulatory notices are Tier 0 when retrieved from the publisher. |
| Fiscal, debt and tax | US Treasury and debt offices, China MOF, European Commission/ECOFIN, national finance ministries and parliamentary budget authorities | `official.fiscal.read`, `official.document.read`, `calendar.event.read` | Budgets, tax measures, debt issuance/auctions and fiscal statements retain jurisdiction and legal-status metadata. |
| Trade, tariffs and customs | WTO, UN Comtrade, USTR, USITC, EU trade authorities, China MOFCOM/GACC and national customs agencies | `official.trade.read`, `official.statistics.read`, `calendar.event.read` | Distinguish policy/legal documents from reported trade statistics and preserve revision/publication timing. |
| Sanctions and export controls | US Treasury OFAC, US BIS, EU Council/Commission, UK OFSI, UN Security Council and jurisdictional authorities | `official.sanctions.read`, `official.document.read` | Lists/actions/amendments are immutable versions. Entity matching is evidence, not authority to rewrite the official source. |
| Securities, banking and market regulation | SEC, CFTC, Federal Reserve/OCC/FDIC, ESMA/EBA, FCA/PRA, CSRC/NFRA/SAFE, SFC/HKMA and official exchanges | `official.regulatory.read`, `official.feed.read` | Rules, consultations, enforcement and market notices require regulator/jurisdiction/action identity. |
| Official statistics | BLS, BEA, Census, Eurostat, NBS China, national statistics offices, World Bank, IMF, OECD and BIS | `official.statistics.read`, `macro.series.read`, `macro.vintage.read` | Prefer originating agency releases; aggregator series retain their upstream definition and vintage semantics. |
| Energy and strategic commodities | EIA, IEA, OPEC, energy ministries, grid/pipeline authorities and official inventory/release sources | `official.energy.read`, `market.commodity.read`, `calendar.event.read` | Separate physical/statistical releases from licensed market benchmarks and futures prices. |
| International and geopolitical institutions | UN/UNSC, WTO, IMF, World Bank, OECD, BIS, G7/G20 and official treaty/institution portals | `official.document.read`, `official.feed.read`, `official.sanctions.read`, `event.radar.read` | Official communiqués/actions are Tier 0; GDELT/media observations remain radar candidates linked for verification. |
| Listed companies and management | SEC EDGAR, CNINFO, HKEX/exchange announcement services, verified issuer IR sites | `official.issuer.read`, `official.document.read`, `calendar.event.read` | Filings and issuer-hosted releases/statements are attributable evidence. Transcripts from third parties retain their lower authority and license. |

## Open-source candidates

Repository activity was checked on 2026-09-21. A library license governs its code, not the right to
redistribute or commercially use upstream data.

| Candidate | Upstream(s) actually used | License / observed activity | Use in AIC |
| --- | --- | --- | --- |
| [`akfamily/akshare`](https://github.com/akfamily/akshare) | Many, including Eastmoney and Sina | MIT; active through 2026-09-20 | High-value protocol/fixture reference. Avoid importing its broad dependency surface for the first quote adapters. Each function must declare its real upstream. |
| [`Micro-sheep/efinance`](https://github.com/Micro-sheep/efinance) | Primarily Eastmoney | MIT code; active through 2026-07-17; README limits use to study/non-commercial contexts | Reference only pending upstream and usage-right review. It is the same Eastmoney vote as an AKShare Eastmoney function. |
| [`shidenggui/easyquotation`](https://github.com/shidenggui/easyquotation) | Sina, Tencent and other feeds | MIT; active through 2026-02-28 | Focused protocol reference for Sina/Tencent. Prefer small owned adapters after tests and terms review. |
| [`1nchaos/adata`](https://github.com/1nchaos/adata) | Multiple public sources | Apache-2.0; active through 2025-12-26 | Reference for failure handling and mappings. “Multi-source” is not sufficient; record each actual upstream per observation. |
| [`mortada/fredapi`](https://github.com/mortada/fredapi) | FRED/ALFRED official API | Apache-2.0; active through 2026-01-28 | Useful semantics reference. Direct official HTTP is preferred to preserve exact vintage/lineage behavior without a pandas dependency. |
| [`gw-moore/pyfredapi`](https://github.com/gw-moore/pyfredapi) | FRED/ALFRED official API | MIT; active through 2026-02-23 | Secondary contract/reference candidate; same upstream as `fredapi`, therefore one authority. |
| [`dr-leo/pandaSDMX`](https://github.com/dr-leo/pandaSDMX) | Many official SDMX endpoints | Apache-2.0; last observed push 2023-12-28 | Standards reference only in the first spike; reevaluate maintenance and dependency cost before adoption. |
| [`sdmx-twg/sdmx-rest`](https://github.com/sdmx-twg/sdmx-rest) | SDMX REST standard | Specification/reference repository; active through 2026-09-11 | Normative protocol reference, not a runtime data source or independent authority. |
| [`dgunning/edgartools`](https://github.com/dgunning/edgartools) | SEC EDGAR | MIT; active through 2026-09-17 | Useful filing/XBRL behavior reference or optional accelerator after dependency review. Authority remains SEC. |
| [`sec-edgar/sec-edgar`](https://github.com/sec-edgar/sec-edgar) | SEC EDGAR | Apache-2.0; active through 2025-12-09 | Download/workflow reference. Same SEC upstream; does not create independent confirmation. |
| [`jadchaar/sec-edgar-downloader`](https://github.com/jadchaar/sec-edgar-downloader) | SEC EDGAR | MIT; active through 2026-06-22 | Focused retrieval reference. Direct SEC contract remains preferred for V1. |
| [`linwoodc3/gdeltPyR`](https://github.com/linwoodc3/gdeltPyR) | GDELT | GPL-3.0; last observed push 2023-11-30 | Do not add as a runtime dependency. Use official GDELT downloads/API with an owned adapter. |

## Official primary sources

| Source | Official contract reviewed | Planned use |
| --- | --- | --- |
| FRED/ALFRED | [FRED API](https://fred.stlouisfed.org/docs/api/fred/), [series observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html), [vintage dates](https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html) | Series, releases, realtime periods and revisions |
| OECD | [OECD API guidance](https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html), [SDMX API](https://sdmx.oecd.org/public/swagger/index.html?urls.primaryName=v2) | Official macro series through SDMX |
| IMF | [IMF API resource](https://data.imf.org/en/Resource-Pages/IMF-API) | Official macro series; authentication/current endpoint validation required |
| BIS | [BIS SDMX API](https://stats.bis.org/api-doc/v2/), [terms](https://data.bis.org/help/legal) | Rates, credit, liquidity and related series |
| ECB | [ECB Data API](https://data.ecb.europa.eu/help/api/overview), [ECB RSS](https://www.ecb.europa.eu/home/html/rss.en.html) | Macro observations and policy publications |
| US Treasury / Federal Reserve rates | [Treasury daily rates and XML/CSV](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve), [Federal Reserve nominal yield curve](https://www.federalreserve.gov/data/nominal-yield-curve.htm) | Official sovereign-yield curve observations |
| ECB FX | [ECB SDMX web services](https://data.ecb.europa.eu/help/getting-data-web-services-sdmx-0), [data API](https://data.ecb.europa.eu/help/api/data) | Official euro reference FX series; not an executable market quote |
| EIA | [EIA Open Data](https://www.eia.gov/opendata/), [API documentation](https://www.eia.gov/opendata/documentation.php) | WTI/Brent references, inventories, supply/demand and scheduled energy evidence |
| Cboe | [VIX historical data](https://www.cboe.com/tradable_products/vix/vix_historical_data), [VIX product page](https://www.cboe.com/tradable-products/vix) | Volatility benchmarks subject to explicit market-data rights; no automated extraction from prohibited delayed pages |
| Federal Reserve | [Federal Reserve feeds](https://www.federalreserve.gov/feeds/feeds.htm), [FOMC calendars/documents](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) | Statements, minutes, decisions and speeches |
| BOJ | [Bank of Japan](https://www.boj.or.jp/en/), [press releases and speeches](https://www.boj.or.jp/en/about/press/index.htm) | Official policy documents and speeches |
| PBOC | [People's Bank of China](https://www.pbc.gov.cn/) | Official policy pages and documents |
| BLS / BEA | [BLS release schedules](https://www.bls.gov/schedule/), [BEA release schedule](https://www.bea.gov/news/schedule) | Economic `ScheduledEvent` records and actual official releases |
| Eurostat | [Eurostat API guidance](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-introduction) | EU statistics and release evidence; the current API exposes latest data without native historical versions, so AIC observation history is mandatory |
| WTO / UN Comtrade | [WTO API portal](https://apiportal.wto.org/), [UN Comtrade API](https://uncomtrade.org/docs/un-comtrade-api/) | Official trade statistics, tariffs and release/update evidence; access tiers and quotas remain explicit |
| OFAC | [OFAC Sanctions List Service](https://ofac.treasury.gov/sanctions-list-service) | Official sanctions lists and amendments |
| IEA | [IEA Energy Statistics Data Browser](https://www.iea.org/data-and-statistics/data-tools/energy-statistics-data-browser) | International energy statistics subject to dataset-specific licenses |
| SEC EDGAR | [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [fair-access guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions) | Submissions, filings and company XBRL facts |
| CNINFO | [CNINFO disclosure search](https://www.cninfo.com.cn/new/commonUrl?url=disclosure%2Flist%2Fnotice) | China listed-company official disclosures, subject to machine-access review |
| GDELT | [GDELT data](https://www.gdeltproject.org/data.html), [DOC 2.0 API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) | Event discovery/radar only |

## Dependency recommendation

1. Use the existing owned HTTP client for Checkpoint A and the first FRED/REST adapters.
2. Start the SDMX work with official JSON/CSV contracts and a bounded parser spike. Add an SDMX SDK
   only after maintenance, license, typing and dependency review proves a lower total risk.
3. Select a hardened XML/RSS parser only when an official source lacks JSON/CSV; apply payload and
   entity-expansion limits and keep parsing in the adapter boundary.
4. Do not add a broad market-data package solely to access one endpoint. Port only the protocol
   knowledge needed by an owned adapter, respecting its license and upstream terms.
5. No commercial purchase is recommended for the first wave. Reassess only if free/official sources
   fail an approved latency, history, PIT, completeness, licensing or availability target. Realtime
   global index, benchmark commodity and volatility coverage is a likely licensed-data exception.

## Investigation risks

- Public market endpoints are operationally brittle and may restrict automated/commercial use.
- Endpoint fields can change without versioning; fixture drift detection and canary health are mandatory.
- Official macro definitions differ even for similarly named series; never reconcile unlike definitions.
- IMF API migration/authentication and CNINFO machine access need explicit contract validation.
- Official index, LBMA, exchange futures and volatility data often have display/redistribution rights
  distinct from API or realtime use; each adapter needs a recorded contract basis.
- Eurostat exposes the latest dataset rather than historical versions, so AIC must preserve every
  observed version to provide PIT behavior.
- Scheduled calendars can be revised without a stable change feed; overlap polling and immutable
  schedule versions are required.
- Publication timestamps are sometimes date-only or altered on page updates; conservative availability
  and immutable content versions are required.
- Library activity and license do not establish upstream data rights, SLA or correctness.
