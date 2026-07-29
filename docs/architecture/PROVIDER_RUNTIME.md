# Provider Runtime

## Implemented boundary

SPEC-003 Phase 1 defines the framework-independent runtime vocabulary and
contracts. Phase 2 adds in-process registration and explicit provider
construction. The runtime does not initialize, check, select, invoke, or expose
providers through HTTP yet.

The package intentionally uses a flat Python structure:

```text
provider_runtime/
|-- models.py       immutable metadata, capability, health and audit values
|-- interfaces.py   lifecycle, invocation, runtime, metrics, clock and ID ports
|-- errors.py       stable error taxonomy
|-- registry.py     atomic registration and immutable snapshots
|-- factory.py      explicit implementation allowlist
|-- system.py       UTC clock and UUID implementations
`-- __init__.py     public contract surface
```

The base `Provider` protocol owns identity, capabilities and lifecycle only.
Business calls use the separate `ProviderInvocationHandler`, preventing the
base protocol from accumulating vendor or domain-specific methods.

Provider Runtime remains independent of FastAPI, Pydantic, Bootstrap,
Infrastructure and concrete Providers. Domain does not depend on Provider
Runtime. Composition and the compatibility adapter for the existing
`DataProvider.fetch()` port are deferred to later approved phases.

## Phase 2 registration semantics

- `ProviderDefinition` validates identity, implementation name, capability
  declarations, priority, concurrency, queue timeout, and copies configuration.
- `ProviderFactory` accepts a copied map of approved builders. It never imports
  arbitrary modules and rejects providers that differ from their definition.
- `ProviderRegistry` performs atomic register and unregister operations under
  an async lock. It never calls Provider lifecycle or health methods.
- Registration captures immutable metadata and capabilities. Read operations
  return snapshots sorted by Provider ID and do not expose registry internals.
- An enabled Provider starts as `REGISTERED`; a disabled Provider starts as
  `DISABLED`. No other state transition exists in Phase 2.
