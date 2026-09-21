# Providers

## Responsibility

Obtain data from one source by implementing an Application-owned provider port.

## Boundary

A provider maps one source contract into AIC-owned output and returns it through Provider Runtime.
It does not decide factual consensus, PIT visibility or persistence.

Deterministic Mock records live in the dedicated `fixtures.py` module, outside
the Bootstrap composition root. The fixture builder returns fresh objects and
does not use random generation.

## Checkpoint A quote sources

Eastmoney, Sina and Tencent have separate adapters and real upstream identities. Their deterministic
fixtures are used in required tests. Production definitions remain disabled until machine-access and
commercial-use rights for the upstream are explicitly approved; an open-source library license is
never evidence of upstream data rights. Multiple adapters or libraries over one upstream remain one
reconciliation vote.

## Checkpoint C policy and event sources

The Federal Reserve adapter reads only the Board's allowlisted official RSS endpoints. It supports
conditional requests, bounds response size and item count, rejects DTD/entity expansion, and emits
official document metadata rather than interpreted policy conclusions.

The SEC EDGAR adapter calls `data.sec.gov` directly, requires `AIC_SEC_USER_AGENT`, preserves CIK,
accession, form and acceptance time, follows only validated submissions cursors, and observes the
SEC fair-access contract. It has no third-party EDGAR runtime dependency.

The GDELT adapter calls DOC 2.0 directly and emits `RADAR_ONLY` candidates. GDELT cannot create or
overwrite verified official evidence. A later official document is connected through an immutable
event-document link.

CNINFO remains unregistered until its machine-access and production-use terms are documented. The
absence of an approved adapter never falls back to a reverse-engineered endpoint.

## Prohibited

- Caching, persistence, event publication, calculations, or use-case decisions
- Imports from Presentation or Infrastructure
- Treating provider failover, adapter count or library count as independent factual corroboration
- Enabling undocumented public endpoints without an explicit upstream authorization record

## Future extension

Each approved source receives a separate adapter behind the existing Provider Runtime.
Replacing the configured adapter must not require Application changes.
