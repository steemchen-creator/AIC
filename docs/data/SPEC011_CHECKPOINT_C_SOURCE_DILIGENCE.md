# SPEC-011 Checkpoint C Source Diligence

Status: engineering evidence for Checkpoint C, reviewed 2026-09-22.

## Production source decisions

| Adapter ID | Upstream source ID | Authority | Access and license finding | PIT identity | Checkpoint C decision |
| --- | --- | --- | --- | --- | --- |
| `fed_official` | `FEDERAL_RESERVE` | Tier 0 / primary | The Board publishes [official RSS feeds](https://www.federalreserve.gov/feeds/feeds.htm). The adapter stores bounded feed metadata, hashes and canonical links; broader redistribution rights are not inferred. | Publisher item ID, publication time, first observation and ingestion time | Enable as an official metadata/feed adapter; allowlisted HTTPS endpoints only. |
| `sec_edgar` | `SEC_EDGAR` | Tier 0 / official API and files | The [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) are public and keyless. [Fair-access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) requires a declared User-Agent and caps aggregate access at 10 requests/second. SEC states government-created and public filing content is free to access and reuse. | Requested/returned CIK, accession, form, acceptance time, source URI, observed and ingested time | Direct owned adapter; `AIC_SEC_USER_AGENT` required; scheduler policy must remain below the upstream aggregate limit. |
| `gdelt_radar` | `GDELT` | Tier 2 / radar | [GDELT terms](https://gdeltproject.org/about.html) permit academic, commercial and government dataset use without fee, with citation/link required on redistribution. DOC 2.0 is a discovery API, not an official fact source. | Source URL digest, event time reported by GDELT, detection/observation/ingestion time | Enable as discovery only; every record remains `RADAR_ONLY` until linked to separate Tier-0 evidence. |
| none | `CNINFO` | Intended Tier 0 | Public disclosure pages exist, but a stable documented machine contract and production-use terms were not established in this review. | Would require issuer/security ID, announcement ID and publication/observation time | No production adapter in Checkpoint C. Do not use undocumented reverse-engineered endpoints. |

## Upstream independence

`edgartools`, `sec-edgar` and `sec-edgar-downloader` all read SEC EDGAR and therefore represent one
upstream authority. `gdeltPyR` reads GDELT and cannot provide independent confirmation of a GDELT
candidate. The first implementation uses owned HTTP adapters and existing `httpx`; no runtime
dependency is added.

Open-source review:

- [`dgunning/edgartools`](https://github.com/dgunning/edgartools): MIT, active, useful behavior
  reference. It requires an SEC identity and does not replace SEC terms or authority.
- [`sec-edgar/sec-edgar`](https://github.com/sec-edgar/sec-edgar): Apache-2.0 workflow reference;
  same SEC upstream.
- [`jadchaar/sec-edgar-downloader`](https://github.com/jadchaar/sec-edgar-downloader): MIT focused
  retrieval reference; same SEC upstream.
- [`linwoodc3/gdeltPyR`](https://github.com/linwoodc3/gdeltPyR): GPL-3.0 and materially less active;
  excluded as a runtime dependency. The owned adapter uses the official API contract.

## Failure and retention policy

- Network, timeout, rate-limit, malformed JSON/XML, oversized payload and identity failures map to
  explicit Provider Runtime failures. Existing evidence is never deleted.
- Official identity mismatches fail closed before canonical persistence. Unknown or ambiguous
  entities are not guessed from titles.
- Raw observations persist before canonical documents/candidates. Deterministic identities make
  retries idempotent.
- Corrections append a document version only with a publisher version identity or an explicit,
  deterministic predecessor. A changed payload cannot silently replace an existing version.
- GDELT candidates retain their radar authority after an official verification link is added; the
  link does not mutate either evidence record.
