# ADR-0000: Project Decision Principles

- Status: Accepted
- Date: 2026-07-28
- Decision owners: AIC maintainers

## Context

AIC is intended for long-term development. Important decisions need a durable record so future contributors understand why a direction was chosen, what alternatives were considered, and when it may be revisited.

## Decision

Use Architecture Decision Records for decisions that materially affect project structure, cross-component contracts, security, operations, data, or long-term maintainability.

### Numbering

- ADRs use four-digit, sequential identifiers: `ADR-0000`, `ADR-0001`, `ADR-0002`, and so on.
- Identifiers are never reused, including after rejection or supersession.
- Filenames use `ADR-NNNN-short-title.md`.

### Lifecycle and status

An ADR moves through: `Proposed` -> `Accepted` or `Rejected`. An accepted ADR may later become `Deprecated` or `Superseded` by a newer ADR. Historical records are retained.

### Review process

1. Describe the context, decision, alternatives, impact, and risks in a Proposed ADR.
2. Open a Pull Request and request review from the relevant owners.
3. Resolve material concerns and record the final outcome.
4. Merge only after the ADR status and consequences are agreed.

## Consequences

Decisions become discoverable and reviewable, at the cost of maintaining concise records as the project evolves.
