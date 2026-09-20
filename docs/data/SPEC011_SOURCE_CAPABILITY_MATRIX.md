# SPEC-011 First-Wave Source and Dependency Matrix

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
| Federal Reserve | [Federal Reserve feeds](https://www.federalreserve.gov/feeds/feeds.htm), [FOMC calendars/documents](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) | Statements, minutes, decisions and speeches |
| BOJ | [Bank of Japan](https://www.boj.or.jp/en/), [press releases and speeches](https://www.boj.or.jp/en/about/press/index.htm) | Official policy documents and speeches |
| PBOC | [People's Bank of China](https://www.pbc.gov.cn/) | Official policy pages and documents |
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
   fail an approved latency, history, PIT, completeness, licensing or availability target.

## Investigation risks

- Public market endpoints are operationally brittle and may restrict automated/commercial use.
- Endpoint fields can change without versioning; fixture drift detection and canary health are mandatory.
- Official macro definitions differ even for similarly named series; never reconcile unlike definitions.
- IMF API migration/authentication and CNINFO machine access need explicit contract validation.
- Publication timestamps are sometimes date-only or altered on page updates; conservative availability
  and immutable content versions are required.
- Library activity and license do not establish upstream data rights, SLA or correctness.
