# Providers

## Responsibility

Obtain data from one source by implementing an Application-owned provider port.

## Boundary

A provider maps source output into Domain objects and returns them. TASK-002
contains only a deterministic mock implementation.

Deterministic Mock records live in the dedicated `fixtures.py` module, outside
the Bootstrap composition root. The fixture builder returns fresh objects and
does not use random generation.

## Prohibited

- Caching, persistence, event publication, calculations, or use-case decisions
- Imports from Presentation or Infrastructure
- Real vendor, market-data, stock, news, financial, or AI integrations

## Future extension

Each approved source receives a separate adapter implementing `DataProvider`.
Replacing the configured adapter must not require Application changes.
