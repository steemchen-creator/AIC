# REVIEW-DEV-GOV-001 — Bootstrap CI Scope Fix

Version: 1.0, 2026-09-07

Author role: CTO / Chief Engineering Officer (Codex)

Authority status: engineering correction submitted for Chief Investment Architect
Architecture Review. This document does **not** grant Architecture Final Approval,
Chairman approval, merge permission, Bootstrap permission, pipeline activation or
SPEC-010 authorization.

## 1. Review Decision Requested

Review the focused correction for `BOOTSTRAP_CI_NOT_PASSED`: required CI is now derived
only from the effective required checks and the GitHub Actions workflow runs corresponding
to those required checks. Approve or return scoped corrections for the exact PR HEAD
reported externally with this package.

Recommended engineering disposition: **APPROVED CANDIDATE**, subject to successful
exact-HEAD GitHub Actions and independent Architecture Review.

## 2. Baseline and Scope

- Baseline `main`: `2f0fda00ccf12cb129a76615f3b4232167ede73b`.
- Branch: `feature/dev-gov-001-bootstrap-ci-scope-fix`.
- Trigger: first protected DEV-GOV Bootstrap returned `BOOTSTRAP_CI_NOT_PASSED`.
- Changed behavior: `GitHubClient.ci()` workflow relevance only.
- Supporting changes: focused tests, this REVIEW, overview clarification and changelog.

No investment functionality, public interface, database, migration, desktop code,
workflow definition, activation configuration or runtime state is changed. Bootstrap is
not executed or bypassed. `automation/dev-state` is not created. Pipeline and Auto Merge
remain OFF. SPEC-010 is not started.

## 3. Root Cause

The adapter correctly discovered and filtered the effective required checks, but it fetched
and included every workflow run emitted by the trusted GitHub Actions app in the final PASS
conjunction. The non-required `AIC Development Orchestrator / orchestrate` workflow is
legitimately skipped while the pipeline is disabled. Its `skipped` result therefore blocked
Bootstrap even though all four required checks were successful.

The defect was an evidence-scope error, not a failure of the required checks themselves.

## 4. Correction

For each raw check, the adapter still retains the check record for observability. It fetches
a workflow run for CI qualification only when the check name is in the effective required
set and its app ID matches both the required binding and the trusted GitHub Actions app ID.

The final PASS decision still requires:

1. the exact effective required-check name set;
2. `success` for every relevant required check;
3. the exact PR HEAD SHA for every relevant required check;
4. the trusted/required app ID for every relevant required check;
5. a corresponding workflow run for each relevant GitHub Actions check;
6. the exact PR HEAD SHA for every corresponding workflow run; and
7. `completed` plus `success` for every corresponding workflow run.

A completed required workflow with a non-success conclusion is reported as `FAILED`.
Incomplete or stale required evidence remains non-passing. A missing required workflow API
record remains a hard error. Non-required workflow state is neither fetched nor used for the
required-CI verdict.

## 5. Security Invariants

The correction does not relax:

- policy plus live GitHub required-check discovery;
- exact required-name equality;
- trusted app ID and per-check required-app binding;
- check-run exact HEAD lock;
- required check `success`;
- corresponding workflow-run exact HEAD lock;
- corresponding workflow `completed` and `success`;
- missing/stale/failed required evidence fail-closed behavior; or
- downstream exact-head eligibility and merge guards.

No branch-protection setting, required-check setting, credential scope or administrative
control is changed.

## 6. Regression Evidence

Focused GitHub adapter tests: **42 passed**.

Positive matrix:

- four required trusted checks `success` on the exact HEAD;
- their corresponding trusted workflow is `completed/success`; and
- an additional non-required trusted workflow is respectively `skipped`, pending or failed.

All three non-required states leave required CI `PASSED`, and the adapter proves it does not
fetch the unrelated workflow run.

Reverse matrix remains fail closed:

- required check failed: `FAILED`;
- required workflow failed: `FAILED`;
- required check stale SHA: not passed;
- required workflow stale SHA: not passed;
- required check missing: not passed;
- required workflow pending: not passed; and
- required workflow API record missing: hard failure.

## 7. Local Validation

- Governance, architecture and branch-coverage suite: **282 passed**.
- DEV-GOV package combined coverage: **96.0952%**.
- `github.py` combined statement/branch coverage: **93.0736%**.
- Critical targets `state_machine.py`, `gates.py`, `ci_gate.py`, `budget.py`, `store.py`
  and `deployment.py`: **100%**, coverage gate passed.
- Non-database repository suite: **828 passed**.
- DEV-GOV source/test Ruff format check: **passed** (`26 files already formatted`).
- Ruff lint: **passed**.
- Strict Mypy: **passed** (`141 source files`).

The complete local pytest command was also run: **843 passed, 10 failed, 30 errors**.
Every failure/error was in PostgreSQL migration/persistence setup because this workstation
has neither `AIC_DATABASE_URL` nor a Docker/PostgreSQL service, and its shell does not expose
the bare `alembic` executable. This is an environment limitation, not recorded as a passing
full-suite result. The exact-HEAD `Backend tests` GitHub Actions job supplies PostgreSQL 17,
runs migrations, the full pytest/coverage suite, Ruff and Mypy, and is required final
evidence.

The WPF Release build is unchanged locally and is validated by the exact-HEAD Windows
`Desktop build` job.

## 8. Exact HEAD / CI Attestation

The immutable commit SHA, Draft PR URL, check-suite run ID, individual job conclusions and
their exact head SHA are supplied externally after the implementation commit. They are not
written back through an evidence-only commit that would invalidate the attested HEAD.

Required final checks:

1. `Governance baseline`;
2. `Backend tests`;
3. `Desktop build`; and
4. `AIC Development Governance Gate`.

Any non-success, missing or stale exact-HEAD evidence must be disclosed and blocks a claim
that exact-HEAD CI passed.

## 9. Risk and Rollback

Primary risk: incorrectly excluding a check that is required under live repository policy.
Controls are live required-check discovery, exact name equality, app binding, SHA binding,
corresponding workflow validation and the reverse regression matrix.

Rollback is a focused revert of the correction commit. That restores the conservative but
incorrect behavior and leaves Bootstrap blocked; it does not authorize bypassing Bootstrap,
creating state manually or enabling the pipeline.

## 10. Stop Conditions

- Do not merge this Draft PR without Chief Investment Architect review and Chairman action.
- Do not enable the pipeline or Auto Merge.
- Do not create or initialize `automation/dev-state` manually.
- Do not retry Bootstrap by bypassing its evidence checks.
- Do not start SPEC-010.

After exact-HEAD evidence is reported, stop and wait for Chief Investment Architect review.
