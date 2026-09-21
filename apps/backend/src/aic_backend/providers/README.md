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

## Prohibited

- Caching, persistence, event publication, calculations, or use-case decisions
- Imports from Presentation or Infrastructure
- Treating provider failover, adapter count or library count as independent factual corroboration
- Enabling undocumented public endpoints without an explicit upstream authorization record

## Future extension

Each approved source receives a separate adapter behind the existing Provider Runtime.
Replacing the configured adapter must not require Application changes.
