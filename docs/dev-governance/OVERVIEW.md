# AIC Autonomous Development Pipeline V1

DEV-GOV-001 is a separate development control plane, not investment functionality.
The full approved specification is archived under docs/specifications. ADR-0007
records the proposed implementation decision; its acceptance still needs review.

## Components

`aic_dev_governance`: models, state_machine, gates, budget, store, orchestrator,
github, workspace, artifacts, bridges, runner, ci_gate, coverage_gate and observability.
There is no dependency from this package to the investment application or vice versa.

The reducer accepts authenticated events; the orchestrator reserves tasks and AI
budgets using CAS before delivery. GitHub comments/issues are consumable task signals.
State, immutable events, requests, architecture JSON/Markdown and debt are durable
on `automation/dev-state`, not on implementation branches.

## Safe defaults and operation

`configs/dev-governance.json` defaults pipeline/merge/Ready/bridge to OFF.
The trusted-main workflow also requires repository variable `AIC_PIPELINE_ENABLED=true`.
Only after the Chairman setup checklist is complete may a separately reviewed policy
enable MANUAL, then DRY_RUN, then explicitly authorized AUTO.

Install with `python -m pip install -e ".[test]"`.
Read local state: `python -m aic_dev_governance status --state-dir tmp/dev-governance/state`.
Read metrics with `metrics`. Run the protected event entry point with `run`; it exits
without effects when disabled. CI uses `gate`, which never writes state or merges.

Bootstrap DEV-GOV-001 is excluded from automatic Ready/Merge and next-SPEC progression.
Its Draft PR, exact HEAD CI, external review and Chairman manual merge remain mandatory.
