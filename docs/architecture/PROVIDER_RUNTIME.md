# Provider Runtime

## Phase 1 boundary

SPEC-003 Phase 1 defines only the framework-independent runtime vocabulary and
contracts. It does not register, initialize, select, invoke, or expose providers
through HTTP yet.

The package intentionally uses a flat Python structure:

```text
provider_runtime/
|-- models.py       immutable metadata, capability, health and audit values
|-- interfaces.py   lifecycle, invocation, runtime, metrics, clock and ID ports
|-- errors.py       stable error taxonomy
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
