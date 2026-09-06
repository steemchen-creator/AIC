# REVIEW-DEV-GOV-001 — Architecture Review Package

Version: 1.0 / implementation submission, 2026-09-07

Author role: CTO / Chief Engineering Officer (Codex)

Authority status: execution authorized; Architecture Review pending. This document
does **not** grant Final Approval, Chairman approval, merge permission or activation.

Specification: [DEV-GOV-001 V1.0](docs/specifications/DEV-GOV-001-AIC-Autonomous-Development-Pipeline-V1.0.md)

## 1. Executive Summary

Implemented a separate, deterministic development control plane with durable state,
SHA-bound review/CI gates, budgeted task adapters, guarded Ready/merge/closeout,
governance incident handling, project memory and recovery. No investment runtime
code, interfaces, database migrations or desktop behavior are changed.

Delivery is a bootstrap Draft PR. All activation switches are OFF. Live model/Work
connections and administrative branch protection are not silently configured.

## 2. Preconditions / SPEC-009 Closeout

Started from clean local main equal to origin/main:
`1b9e3d50921751a9b016fcf4bb82a9d813a2bdd7`.
PR #11 was manually merged at `2026-09-06T17:23:54Z`; its corrected governance record
is in that main commit. The governance branch was removed locally and remotely.

The owner relayed the Chief Investment Architect's final SPEC-009 status:
`FINAL APPROVED WITH NON-BLOCKING DEBT / GOVERNANCE EXCEPTION RECORDED / PROCESS DEVIATION OCCURRED / FORMAL CLOSEOUT COMPLETE`.
This is the authority for the prerequisite, not an approval invented by this implementation.

## 3. Scope

Branch: `feature/dev-gov-001-autonomous-development-pipeline`.
Changes are limited to `aic_dev_governance`, its new tests, CI/configuration,
documentation and packaging of that independent package. Existing business source
and existing regression tests are unchanged. SPEC-010 is not started or generated.
No actual merge, state-branch initialization, paid AI call or bot activation is part
of this bootstrap delivery.

## 4. Architecture

See [ADR-0007 (Proposed)](docs/adr/ADR-0007-autonomous-development-pipeline.md).
Typed models and a pure reducer own decisions; the orchestrator coordinates owned
StateStore, Repository, Workspace and bridge interfaces. GitHub is the durable shared
source of truth. Runtime state is not stored in implementation commits.

Boundary tests reject imports between investment functionality and the governance
package. Privileged processing checks out trusted main only; PR code runs with
read-only credentials in its separate CI job.

## 5. State Store

`LocalFileStateStore`: exclusive writer lock, revision check, one fsynced atomic
snapshot containing state/events/artifacts. `GitHubStateBranchStore`: independent
`automation/dev-state`, immutable artifacts/events and parent-bound non-force ref
update. Conflicting writers fail before external delivery. No blind mutation retry.
Initial state creation uses an independent root commit, not a product HEAD change.

## 6. State Machine

The transition table covers PLANNED through CLOSED plus waiting, blocked, failed and
Chairman-decision states. Guards enforce role, ordering, exact input SHA and evidence.
CI reruns revoke cached eligibility. HEAD changes clear approval and CI, requiring a
new review. Invalid transitions fail rather than silently advancing.
See [state machine](docs/dev-governance/STATE_MACHINE.md).

## 7. Workflow Events

Versioned events record identity, work item, timestamp, input SHA, actor, metadata
and output state. Supported events include SPEC/FIX publication, engineering,
architecture review, CI, Ready/merge/closeout, budgets, incidents, memory updates
and pause/recovery. GitHub workflows serialize reconciliation; critical event
commands require authenticated role mapping rather than an actor in PR text.

## 8. Artifact Protocol

SPEC is hash-pinned at registration. REVIEW, changed text modules, relevant ADRs
and required memory are validated before a review request. Architecture output is
typed JSON plus immutable Markdown; FIX responses become scoped, durable artifacts.
Task reservation and subsequent delivery records are separate immutable artifacts.
See [artifact protocol](docs/dev-governance/ARTIFACT_PROTOCOL.md).

## 9. Project Memory Integration

Added `docs/project/AIC_MASTER_PROJECT_MEMORY_V2.md`, architecture index and technical
debt registry. These reference the existing canonical requirements/ADRs instead of
inventing a replacement investment specification. Every new engineering/review
request reads the required memory. Major architecture, policy, role, roadmap or
incident changes emit a memory-update requirement; ordinary fixes do not rewrite
the entire project memory.

## 10. Review Context Manifest

`REVIEW_CONTEXT.json` binds work item, base/head SHA, changed/deleted files, modules,
SPEC, REVIEW, ADRs, memory references, evidence summaries, debt and review questions.
Each selected file has a SHA-256. Required memory is always supplied; optional cached
content is reusable only under matching hashes. Deleted files remain explicit.

The read-only CI job verifies local selected content against immutable GitHub HEAD
blobs and uploads `review-context-<exact HEAD>`. The manifest is external evidence,
not a self-referential evidence-only commit. CI status inside this pre-completion
manifest can be UNKNOWN; final check/run results are attested separately.

## 11. ChatGPT Bridge

Three implementations exist: MANUAL_BRIDGE, CHATGPT_WORK_EVENT_BRIDGE and
OPENAI_API_BRIDGE. Manual/unavailable mode enters the explicit waiting state.
Work mode publishes a durable GitHub task signal for an independently authorized
consumer; it does not invent a ChatGPT Work API or claim delivery to an unconnected account.

The API adapter follows the official Responses structured-output contract, with
strict schema, explicit model/authorization, bounded timeout/output and no automatic
paid-call retry. Refusals, incomplete results, malformed schema and SHA mismatch
fail closed. This interface is mock-tested; no live API call has been made.

## 12. Codex Bridge

The engineering adapter publishes a consumable GitHub issue/comment and immutable
task reference for SPEC_READY/FIX_READY. The contract requires memory/SPEC/FIX reads,
implementation, tests, docs, REVIEW and a Draft PR. The consumer receives no approval
or merge authority. An external authorized engineering worker is an explicit setup
dependency, not a claim that posting a comment itself executes Codex.

## 13. GitHub Integration

The owned HTTP adapter covers PR identity/state, check runs/workflow runs, effective
required checks, refs, immutable files/trees, expected-SHA squash, Ready/Draft and
task transport. Reads have bounded retries; writes are single-attempt. Unexpected
permissions, pagination limits and failures are surfaced. Credentials are supplied
only by the protected environment and are not included in logs or review context.

## 14. SHA Lock

Approval requires `reviewed_head_sha == current HEAD`; eligibility requires
`approved_head_sha == current HEAD == CI head`. The merge request supplies the
expected HEAD to GitHub. A later push invalidates prior approval and restores Draft
where necessary. API uncertainty is reconciled against actual PR state, not assumed
successful or resent with an unapproved SHA.

## 15. CI Gate

CI evidence includes actual check-run identity/app and workflow run ID, SHA, attempt,
status, conclusion and URL. Required names come from policy plus effective GitHub
rules/classic protection. Missing, stale, failing or incomplete evidence blocks.
Missing main protection separately yields `ADMIN_SETUP_REQUIRED` for eligibility.

The read-only `AIC Development Governance Gate` validates identity/artifact/state;
it does not confuse a passing implementation check with Architecture Approval and
does not create a circular dependency on its own final result.

## 16. Merge Eligibility

The deterministic evaluator checks final approval, exact SHA/CI, discovered required
checks, protection, open non-Draft PR, no unresolved FIX/blocking debt, no exception,
no Chairman escalation, no exhausted budget, predecessor CLOSED and enabled/healthy
state. Ready-candidate evaluation relaxes Draft only for that operation. Labels and
PR prose are display data, never authority. Failed gates return explicit reasons.

## 17. Auto Merge

Implemented MANUAL, DRY_RUN and AUTO policies, with explicit merge enablement,
squash-only expected-SHA mutation and no force bypass. Defaults are MANUAL/OFF.
DEV-GOV-001 is unconditionally excluded from automatic Ready/Merge. No GitHub
Auto Merge setting or PR Auto Merge request is enabled by this task.

## 18. Chairman Gate

Master Requirement, investment/risk permissions, live broker/leverage, core
architecture and governance/security changes require Chairman intervention.
Classification examines real changed paths, not just author-supplied labels.
Pause, disable-auto-merge and recovery are separately authenticated. A protected
delegation can authorize a standard future work item; no such delegation is present
in this delivery, and model-generated text cannot supply it.

## 19. Closeout

Closeout checks actual merged PR, approved HEAD, merge commit/tree equivalence,
latest main, local/origin equality and clean workspace. Local and remote feature
branch cleanup is limited to the approved branch/head; evidence is persisted outside
implementation history. Only after successful cleanup is CLOSED emitted. Tree
differences or unmerged branch work stop cleanup for review.

GitHub REST branch deletion has no expected-SHA parameter: a narrow read/delete
race remains. Activation requires single-writer ownership during closeout. Local
ref deletion uses an expected-old-SHA comparison. This limitation is not hidden.

## 20. Next Spec Trigger

Only healthy CLOSED work can request a next SPEC. Proposals are budgeted and archived
without becoming execution authorization. Registration/publication requires separate
Chairman authority or an explicitly reviewed protected delegation. Bootstrap import
does not emit NEXT_SPEC_REQUESTED. No SPEC-010 work was started by this implementation.

## 21. AI Budget

Defaults: three review loops per work item, five architecture calls per work item,
two new SPEC calls per UTC day and a 30-minute duplicate-event window. Reservations
are durable before calls; limits escalate to Chairman without another call.
Only known pre-call bridge unavailability refunds a reservation. Unknown network or
crash outcomes retain their reservation and are not automatically retried.

## 22. Deduplication

Event IDs are permanently idempotent; typed work-item/SHA/stage duplicates are
window-deduplicated. Content-derived task keys survive restarts. CAS chooses a single
winner before delivery, including two concurrent orchestrators. GitHub transport
markers supplement the durable outbox; a copied marker is not authorization.

## 23. Retry

GETs use bounded backoff (three attempts by default, hard upper bound five); writes
are not blindly retried. An uncertain reserved model request requires reconciliation
and authorized recovery, preserving at-most-once dispatch preference over availability.
The runner has a bounded eight-tick invocation, not an infinite agent conversation.

## 24. Failure Modes

Covered failures include GitHub unavailable/403, stale SHA/CI, missing artifacts,
malformed/refused API results, branch drift, tree mismatch, store conflict, crash,
permission denial, budget exhaustion and unexpected PR closure. They block/pause,
wait or escalate with recorded reasons. Failures while requesting a successor do
not reopen an already CLOSED predecessor. Emergency OFF prevents further effects.

## 25. Governance Exception

PR_MERGED_EARLY creates a governance exception and pauses the pipeline. No normal
closeout, branch cleanup or next-SPEC transition follows. Recovery requires explicit
governance handling and independent authority; successful tests or execution
authorization cannot retroactively supply Final Approval.

## 26. Security

Pipeline and merge defaults are OFF; role maps are empty except the non-approving bot.
Protected workflow configuration comes from main, never PR payloads. API and GitHub
secrets are environment-only. Artifacts reject secret-like keys, binaries, .env,
caches, generated output, traversal and unsafe local symlinks. Git operations use
allowlisted argument vectors, never generated shell commands.

## 27. Prompt Injection Defense

Manifest trust notices explicitly separate repository data from authority. PR bodies,
comments and model output cannot grant tools, override policy or impersonate Chairman.
Strict typed ingestion and independent role authentication remain mandatory. The
allowlist/secret patterns are defense in depth, not a claim to recognize every secret
or every malicious natural-language instruction. External consumers must preserve
the same trust boundary.

## 28. Audit Timeline

Immutable events, reviews, FIX/SPEC results, task reservations/deliveries and closeout
records are stored with revisions. Metrics derive merge attempts/failures, budget
usage and phase durations from events. Available API token usage is persisted;
unavailable usage/cost/timing remains unknown. Logs exclude secrets and model content.
Dashboard/CLI reads do not invoke models.

## 29. Technical Debt Registry

Runtime non-blocking review items append structured debt records with origin,
severity, blocking status, target phase and status. Static deployment debt is in
`docs/project/TECHNICAL_DEBT.md`: main protection and external bridge setup.
These are implementation-reported activation limitations; their classification
does not pre-empt the Architect's decision on this PR.

## 30. Memory Recovery

Restart tests construct a fresh orchestrator using only persisted state plus
repository evidence. Approval, SHA, CI, budgets, events, task/result artifacts and
debt remain available. Stored API results can be ingested after a crash without a
second paid call. Unknown reservations are not automatically redelivered. See
[disaster recovery](docs/dev-governance/DISASTER_RECOVERY.md).

## 31. Premature Merge Regression

Regression recreates candidate approval followed by an externally merged PR.
Expected outcome: BLOCKED, governance_exception=true, PR_MERGED_EARLY, paused
pipeline, no cleanup and no NEXT_SPEC. Tests also exercise approval invalidation
after HEAD drift and rejection of old-SHA review results.

## 32. Test Evidence

Local Python: 3.12.14, isolated `.venv`, editable `.[test]` installation.

```text
python -m pytest apps/backend/tests/dev_governance apps/backend/tests/architecture \
  --cov=aic_dev_governance --cov-report=json:tmp/dev-gov-coverage.json \
  --cov-fail-under=0 -q --tb=short
229 passed

python -m pytest --ignore-glob='*postgresql*' \
  --ignore=apps/backend/tests/persistence/test_migrations.py -q --tb=short
775 passed (explicit non-database subset, NOT a full-suite claim)
```

The first local full-suite attempt could not supply PostgreSQL/AIC_DATABASE_URL
(10 failures and 30 setup errors for that environment); it also exposed one new
fixture identity error, which was corrected. Later audit refinement exposed an
attempt to overwrite an immutable task artifact; delivery is now appended separately.
No existing test was weakened or deleted. Full PostgreSQL validation remains mandatory
in the final-HEAD GitHub backend job, not replaced by the local subset.

E2E tests cover happy path, FIX/re-review at a new SHA, premature merge, repeated
review budget exhaustion, lost chat context/restart and concurrent dispatch.

## 33. Coverage

Local dedicated-suite statement-plus-branch targets are enforced by executable
`coverage_gate.verify_coverage`, not rounded display percentages:

| Module / requirement | Measured baseline | Required |
|---|---:|---:|
| State machine | 100% | 95% |
| Merge gate, SHA lock and CI gate (`gates.py`) | 100% | 100% |
| AI budget | 100% | 95% |
| State store | 100% | 95% |
| GitHub adapter | 92.8889% | 90% |

The complete governance package is approximately 96% including orchestration and
entry points. Whole-repository coverage, including PostgreSQL paths, comes from
the final CI `coverage-<HEAD>` artifact. A failed/local subset run is not presented
as a full-repository coverage result.

## 34. Ruff

`python -m ruff check .`: passed. New Python files were formatted with Ruff.
Existing source/test formatting was not rewritten. CI reruns lint on all backend
source/tests at the submitted revision.

Staged diff validation is clean outside the archived approved SPEC. That archival
copy intentionally retains the source's Markdown hard-break spaces and blank EOF;
its complete normalized text was checked equal to the supplied V1.0 document.

## 35. Mypy

`python -m mypy`: passed, 140 source files under strict configuration. The new
package is included alongside the original 124 source files; no strictness rule
was disabled to accept the new implementation.

## 36. WPF

No desktop source/project change. The local environment has no usable dotnet SDK,
so no local WPF success is claimed. Required evidence is the final-HEAD Windows
CI `dotnet build apps/desktop/AIC.Desktop.csproj --configuration Release` result.

## 37. GitHub Actions

CI retains Governance baseline, full PostgreSQL 17 Backend tests and Windows Desktop
build, and adds AIC Development Governance Gate plus exact-HEAD context/coverage
artifacts. The separate protected orchestrator is disabled until reviewed setup.
Its privileged job never checks out untrusted PR code.

This committed review precedes the commit SHA/CI run it describes. Final run ID,
attempt, head SHA, all four job conclusions and artifact identities are published
in the PR/final external attestation after CI completion. Pending CI is not approval.

## 38. Bootstrap Limitations

The initial PR receives a narrowly scoped read-only bootstrap check, bound to this
work item, branch, clean-main base and Draft state. It cannot approve or merge itself.
The independent state branch does not yet exist. One-time post-merge initialization
requires Chairman identity, actual merged/tree/main/CI evidence, deleted feature
branch and an external Architecture Closeout reference.

## 39. Chairman Setup Required

See [SETUP-DEV-GOV-001-CHAIRMAN.md](SETUP-DEV-GOV-001-CHAIRMAN.md) and
[branch protection checklist](docs/governance/BRANCH_PROTECTION_RECOMMENDATIONS.md).
Administrator must configure protection/no bypass/required checks. Chairman must
select identities, protected environment/token, escalation channel and optional
Work/API consumer. Paid model selection and execution delegation require explicit
decisions. These settings were not changed during implementation.

## 40. Known Limitations

- Live Work/API and bot credentials are not connected; mock integration is not a live run.
- V1 conservatively blocks unknown/missing CI and non-identical merge trees.
- Remote branch cleanup needs single-writer ownership for its read/delete interval.
- Unknown model-call outcomes favor no duplicate call over automatic recovery.
- Context is bounded (200 KB/file, 2 MB/review); unsupported/binary paths stop for review.
- Non-GitHub-Actions status-check providers need an explicitly reviewed adapter/policy;
  no legacy status is guessed successful.
- Core governance changes escalate rather than granting the bot power to change its rules.
- Branch protection and bridge authorization remain deployment prerequisites.

## 41. Final HEAD Requirement

Final delivery must verify local HEAD == origin feature HEAD == PR headRefOid, an
open Draft PR targeting main, successful CI for that exact full SHA, clean workspace
and no Auto Merge request. Any code/doc follow-up changes HEAD and require fresh CI
and review. No evidence-only commit will be added merely to record its own SHA.
The final PR body/response supplies the full immutable SHA and CI links.

## 42. Final Recommendation

Submit the completed implementation and exact-HEAD evidence for Chief Investment
Architect Architecture Review. Review authority separation, state/CAS recovery,
SHA/CI gates, remote cleanup race and activation checklist in particular.
Do not treat this engineering recommendation as Final Approval.

Required stop: keep DEV-GOV-001 Draft/unmerged, Auto Merge OFF, SPEC-010 NOT STARTED;
wait for Chief Investment Architect review and subsequent Chairman manual action.
