# REVIEW — DEV-GOV-RECOVERY-002

## What and why

Add a narrow, Chairman-only recovery for a stale sensitive-diff latch. SPEC-010 PR #19
correctly escalated at `7bafdbe589922209fc2bd1505ac177d7f9f61b66` when its diff included
`docs/project/TECHNICAL_DEBT.md`. The path is absent at
`99756090eeb267d79e33dc8789a00b395ec8f713`, but durable `chairman_required` and
`SENSITIVE_DIFF:master_project_objective` remain. Ordinary `RECOVERY_AUTHORIZED` cannot
recover that incident and retains its existing restrictions.

This PR implements the explicitly requested recovery mechanism on
`feature/dev-gov-recovery-002`, based on main
`ec09fa568f0513d9a0a9548044921d09edaf213c`. It does not execute recovery against live state.

## Trust and architecture boundaries

- Add `SENSITIVE_DIFF_REVALIDATED` to the event taxonomy and Chairman-only event set.
- Existing authenticated `event` command accepts exactly work-item ID, event type and
  explicit HEAD; it rejects path/actor/PR-number/metadata claims.
- Trusted-main `Orchestrator.handle` authenticates Chairman before repository reads, ignores
  caller-supplied PR evidence, and fetches the live registered PR through its owned GitHub port.
- Verify PR number, target branch, repository, open/main identity and exact durable/requested
  HEAD. Read the current diff, invoke the unchanged `classify_changed_paths()`, and reject any
  sensitive area. A second PR fetch rejects head/base/identity changes during the read.
- Include both rename endpoints; refuse the GitHub PR-files API's 3,000-file ceiling instead
  of classifying an incomplete list. Read failures fail closed without state writes.
- The pure reducer requires separately supplied repository evidence, rechecks identity and
  sensitivity, and never treats event metadata as proof. No SQL/network imports are added there.
- Existing compare-and-swap persistence appends the event and state atomically; concurrent
  state writes cannot lose a newly recorded incident.

No new architecture, authority, workflow permissions or state-edit surface is introduced.
This is the user-authorized event extension within ADR-0007's existing control-plane boundaries;
no additional architectural decision requires an ADR.

## Recovery semantics and risks

Only `SENSITIVE_DIFF:*` blocked reasons with matching historical escalation evidence are
eligible. Unrelated blockers, other historical Chairman escalations, budget incidents/counters,
declared sensitive work-item areas, governance exceptions or merge evidence reject the whole
request. This deliberately conservative treatment may require separate authorized handling
for a work item with an old unrelated incident; it never guesses that the other cause ended.

For `RECOVERABLE_FAILURE`, preserve status, recovery stage, recoverable failures and CI exactly.
The existing fresh exact-HEAD CI path subsequently performs normal recovery. For a solely
sensitive `CHAIRMAN_DECISION_REQUIRED`, return to `REVIEW_REQUIRED` or `FIXING` when a FIX
is unresolved. Any prior approval/merge eligibility is invalidated. No Ready, approval, merge,
CI success, budget reset or pipeline resume is created by revalidation.

Historical events, reviews and artifacts remain unchanged. The appended recovery event records
Chairman actor, current HEAD, PR number, base SHA, canonical path digest and path count.
GitHub and state storage are separate systems: reads detect observed PR drift, while state CAS
detects concurrent state writes. A later PR change still requires the existing HEAD/CI gates;
this event is never an approval of a future HEAD.

## Requirement traceability

| Requirements | Implementation and evidence |
|---|---|
| 1–3, 10 | `models.py`, `runner.py`, Chairman authentication and explicit/stale HEAD tests |
| 4–5 | `orchestrator.py`, `github.py`; current PR identity, sensitive paths, pagination/rename, drift, forged-claim and read-failure tests |
| 6–9 | `state_machine.py`; mixed blockers, governance/merge/budget incidents, historical cause, pure Chairman and recoverable failure tests |
| 11 | `test_sensitive_diff_recovery.py`: 55 deterministic regression cases; historical escalation, later clean HEAD, successful revalidation, fresh CI and append-only/CAS evidence |
| 12 | State machine and disaster recovery runbooks, README and changelog |
| 13–16 | Diff contains no SPEC-010 product code, state edits, workflow/branch-protection/Governance Gate changes, approval or merge |

## Validation

Local Python 3.12.14 results before commit:

- `python -m pytest apps/backend/tests/dev_governance/test_sensitive_diff_recovery.py -q`:
  **55 passed**.
- `python -m pytest apps/backend/tests/dev_governance --cov=aic_dev_governance
  --cov-report=json:tmp/recovery002-governance-coverage.json --cov-report=term -q`:
  **327 passed**, statement/branch coverage **96.41%**; state machine **100%**.
- `python -m pytest --ignore=apps/backend/tests/infrastructure --cov
  --cov-report=json:tmp/recovery002-local-coverage.json --cov-report=term -q`:
  **903 passed**, repository statement/branch coverage **92.36%**.
- Existing critical-module coverage verifier: **passed**; state machine, gates, budget,
  store, CI gate and deployment **100%**, GitHub **93.70%**.
- `python -m ruff check apps/backend/src apps/backend/tests`: **passed**.
- `python -m mypy`: **passed**, 141 source files, strict configuration.

The host has no PostgreSQL/Docker/.NET SDK. The unchanged CI backend job runs
`alembic upgrade head`, the **full** `pytest --cov --cov-report=term-missing
--cov-report=json:tmp/coverage.json` suite with PostgreSQL 17, critical coverage gates,
Ruff and strict mypy. The desktop job builds Release with .NET 8. Final exact-HEAD CI
results and `git diff --check` are reported in the Draft PR/final delivery evidence;
no evidence-only commit changes the SHA after that run.

The recovery task may require separate authorized governance registration/attachment.
This implementation does not bypass `WORK_ITEM_NOT_RESOLVED` or the existing sensitive-path
gate for its own PR and does not claim governance approval from successful backend tests.

## Rollback and operations

Before deployment, revert this PR through normal review. There are no database migrations,
new dependencies or automatic live-state changes. After an actual Chairman invocation, old
code cannot deserialize the newly added event enum: do not revert to an old reader against
that state or delete the event. Preserve evidence and use a reviewed forward correction or
a compatibility change retaining the enum.

The runbook includes the exact SPEC-010 example, but only trusted-main code after independent
review/publication and a separate authenticated Chairman invocation may use it. Engineering
does not self-approve, merge, dispatch live recovery or manually edit `automation/dev-state`.
