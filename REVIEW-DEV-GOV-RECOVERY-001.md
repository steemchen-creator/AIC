# REVIEW — DEV-GOV-RECOVERY-001

## Decision requested

Review the exact PR HEAD for a minimal, forward-only way to add
`aic-architect-2` as an authorized Architect while preserving the original DEV-GOV-001
Deployment Setup and every prior state event.

## What changed

- Added a deny-unknown-field `DeploymentPolicyRotation` record and
  `DEPLOYMENT_POLICY_ROTATED` audit event.
- Added full setup-plus-rotation-chain validation and latest-valid-policy materialization.
- Added a store invariant that rotation history may only grow by preserving its exact prefix;
  GitHub state writes one immutable JSON artifact per new rotation.
- Added a dedicated `rotate-policy` entry point and protected manual GitHub Actions workflow.
- Added deterministic success, rejection, tamper and workflow-boundary tests.
- Added the recovery runbook, ADR-0008, README and changelog entries.

## Why

One-time immutable setup is correct for bootstrap integrity but offers no controlled recovery
when a principal account becomes unavailable. Direct state edits, a repeated setup, or mutable
checked-in principals would weaken the governance trust boundary. A Chairman-authenticated,
fingerprint-linked forward append restores an identity without changing prior authorization
evidence.

## Security and architecture invariants

- The external variable must equal `false`; absent, malformed or `true` values fail closed.
- The dispatch actor must equal the protected current Chairman and must also authenticate
  against the chain-tip policy.
- The workflow accepts only `workflow_dispatch` from `refs/heads/main`, checks out `main`
  explicitly and does not persist checkout credentials.
- The proposal is a complete schema-validated non-secret policy. V1 rejects any change outside
  `principals`, as well as duplicate, empty or overlapping role assignments.
- Both fingerprints are canonical SHA-256 values; a stale expected tip or any invalid historical
  link fails closed.
- Ordinary Governance Gate, required checks, SHA locks, Ready and merge behavior are untouched.
- No product/investment package imports the governance control plane or vice versa.

## Authorized target

The documented recovery keeps all existing policy fields and principals, adding only
`aic-architect-2` to `CHIEF_INVESTMENT_ARCHITECT`.

```text
previous: 6df86a26a6681f13612536912cca2d97d1d8afe20a1138cade66fa3d7d741045
proposed: cd6f53c56de55919a15453928bff30187a1ab481400ac5a07d6e0ffe2445233f
```

The feature PR does not execute this transition and does not modify `automation/dev-state`.
Only the protected workflow from merged `main` can append it.

## Risk and rollback

The protected Chairman/environment remains the administrative trust root. CAS or network
failure may require a retry after re-reading the chain tip; a guessed or stale tip is rejected.
Rollback is another reviewed forward rotation restoring the prior principals. Never rewrite
the original setup or delete state history.

## Validation

- Governance suite: 272 passed with 96.24% aggregate coverage; deployment and store reached
  100% statement/branch coverage and every critical coverage threshold passed.
- Full local collection: 905 tests; 865 passed and 40 PostgreSQL/migration cases could not run
  because this workstation has neither PostgreSQL nor Docker. The Draft PR's Backend tests job
  supplies PostgreSQL 17 and is the required full-suite evidence.
- Non-PostgreSQL repository suite: 847 passed. The attempted full-suite coverage was 93.79%,
  above the 90% global threshold despite unavailable database cases.
- `ruff check apps/backend/src apps/backend/tests`: passed.
- `mypy`: passed for all 141 source files.
- `git diff --check`: passed.
- GitHub exact-HEAD CI: required after Draft PR creation.

## Scope exclusions

- No state mutation or Deployment Setup rerun.
- No pipeline activation or Auto Merge.
- No investment code, workflow policy relaxation or SPEC-010/PR #16 change.
- No merge by the implementer.
