# AIC Autonomous Development Pipeline V1

DEV-GOV-001 is a separate development control plane, not investment functionality.
The full approved specification is archived under docs/specifications. ADR-0007
records the proposed implementation decision; its acceptance still needs review.

## Components

`aic_dev_governance`: models, state_machine, gates, budget, store, orchestrator,
github, workspace, artifacts, bridges, deployment, runner, ci_gate, coverage_gate and
observability.
There is no dependency from this package to the investment application or vice versa.

The reducer accepts authenticated events; the orchestrator reserves tasks and AI
budgets using CAS before delivery. GitHub comments/issues are consumable task signals.
State, immutable events, requests, architecture JSON/Markdown and debt are durable
on `automation/dev-state`, not on implementation branches.

## Safe defaults and operation

`configs/dev-governance.json` defaults pipeline/merge/Ready/bridge to OFF.
The trusted-main workflow also requires repository variable `AIC_PIPELINE_ENABLED=true`.
Privileged non-secret deployment values are not committed to mutable product PR config.
A separate protected one-time setup validates and records the full effective policy,
version, identities and SHA-256 fingerprint in state while the normal runner remains OFF.
The repository variable is an independent external kill switch: activation reconstructs
the same policy from state and verifies its fingerprint. The setup schema permits only
MANUAL or DRY_RUN; AUTO/Auto Merge requires a later separate authorization.

Install with `python -m pip install -e ".[test]"`.
Read local state: `python -m aic_dev_governance status --state-dir tmp/dev-governance/state`.
Read metrics with `metrics`. Run the protected event entry point with `run`; it exits
without effects when disabled. CI uses `gate`, which never writes state or merges.

Bootstrap DEV-GOV-001 is excluded from automatic Ready/Merge and next-SPEC progression.
Its Draft PR, exact HEAD CI, external review and Chairman manual merge remain mandatory.

CI PASS is scoped to the effective required-check set and, for required checks emitted by
the trusted GitHub Actions app, their corresponding workflow runs. Every required check
must retain the trusted app binding and exact PR HEAD; every corresponding workflow must
retain the exact HEAD and a completed/success result. Checks and workflows outside the
effective required set remain observable evidence but do not change required-CI status.
Missing, stale, pending or failed required evidence continues to fail closed.

After manual merge/Closeout, a distinct protected `workflow_dispatch` bootstrap job
may create only `automation/dev-state` while the normal pipeline stays disabled. Its
Chairman identity comes from protected environment configuration. Later implementation
PRs are resolved from that durable state; the bootstrap descriptor never changes per SPEC.

After bootstrap, `AIC Development Governance Setup` runs from trusted `main` under a
second protected environment. It requires formal closed-bootstrap state, refuses to run
if the normal pipeline is active, writes one immutable setup transition, and cannot
dispatch, approve, Ready, or merge. The exact ordered operator procedure is in
`SETUP-DEV-GOV-001-CHAIRMAN.md`.
