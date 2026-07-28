# Application Ports

## Responsibility

Define the provider, repository, cache, and event bus contracts required by Application use cases.

## Boundary and prohibitions

Ports may reference Domain types but never concrete adapters, frameworks, SDKs, databases, or transports.

## Future extension

Add only the narrow operation required by an approved use case.
