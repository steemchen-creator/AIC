# Providers

## Responsibility

Obtain data from one source by implementing an Application-owned provider port.

## Boundary

A provider maps source output into Domain objects and returns them. TASK-002
contains only a deterministic mock implementation.

## Prohibited

- Caching, persistence, event publication, calculations, or use-case decisions
- Imports from Presentation or Infrastructure
- Real vendor, market-data, stock, news, financial, or AI integrations

## Future extension

Each approved source receives a separate adapter implementing `DataProvider`.
Replacing the configured adapter must not require Application changes.
