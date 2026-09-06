# AIC Architecture Memory

This is an index, not a competing architecture specification.

- Investment system: [Clean Architecture](../architecture/README.md),
  [Provider Runtime](../architecture/PROVIDER_RUNTIME.md), PIT-only portfolio/execution,
  forward paper accounts, isolated shadow experiments, domestic ETF/index foundation.
- Accepted decisions: [ADR index](../adr/README.md).
- Development control plane: [ADR-0007](../adr/ADR-0007-autonomous-development-pipeline.md)
  and [DEV-GOV overview](../dev-governance/OVERVIEW.md), currently proposed for review.
- No direct US trading, broker/live-trading permission, leverage, AI investment brain,
  or SPEC-010 work is introduced by the development pipeline.

State-machine/gate code is deterministic and does not import HTTP, product infrastructure
or LLM clients. Orchestrator depends on owned repository, workspace and trigger protocols.
Composition/runner chooses adapters from trusted configuration, never PR prose.
