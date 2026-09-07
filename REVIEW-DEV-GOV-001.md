# REVIEW-DEV-GOV-001 — Architecture Review Package

Version: 1.2 / FIX-DEV-GOV-001-002 re-review submission, 2026-09-07

Author role: CTO / Chief Engineering Officer (Codex)

Authority status: second-round Architecture Review = CHANGES_REQUIRED; the authorized
FIX-DEV-GOV-001-002 corrections are implemented and re-review is pending. This document
does **not** grant Final Approval, Chairman approval, merge permission or activation.

Specification: [DEV-GOV-001 V1.0](docs/specifications/DEV-GOV-001-AIC-Autonomous-Development-Pipeline-V1.0.md)

Correction authority: [FIX-DEV-GOV-001-002](docs/dev-governance/FIX-DEV-GOV-001-002-Post-Bootstrap-Activation-and-First-Work-Item-Transition.md),
review target `a38316682e0edb95f2ebe38052d090e0fbf57a3b`. The review explicitly
accepts the three original FIX-001 blocking corrections and identifies the separate
post-bootstrap activation deadlock addressed here.

## 1. Executive Summary

Implemented a separate, deterministic development control plane with durable state,
SHA-bound review/CI gates, budgeted task adapters, guarded Ready/merge/closeout,
governance incident handling, project memory and recovery. No investment runtime
code, interfaces, database migrations or desktop behavior are changed.

Delivery is a bootstrap Draft PR. All activation switches are OFF. Live model/Work
connections and administrative branch protection are not silently configured.
FIX-001 removed the bootstrap identity deadlock, made normal PR identity state-based,
separated recoverable operations from sticky governance failures, and narrowed risk-path
escalation. FIX-002 now removes the post-bootstrap activation deadlock with a protected,
one-time, fingerprinted Deployment Setup and proves the synthetic first-work-item path.

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

Bootstrap now has its own manual protected workflow and CLI path. It never enters
the normal tick loop and requires every activation flag OFF. The normal workflow no
longer exposes initialize. This separates initial state creation from autonomous effects.

The selected FIX-002 design is Option B: privileged non-secret deployment values live in
a protected Environment, outside mutable product PRs. A separate manual setup workflow
validates them, records the complete effective MANUAL/DRY_RUN policy plus version,
Chairman, timestamp and SHA-256 fingerprint, and expires after one state transition. The
normal runner remains externally OFF until an administrator enables its repository kill
switch; at runtime it reconstructs policy from state and verifies the fingerprint.

## 5. State Store

`LocalFileStateStore`: exclusive writer lock, revision check, one fsynced atomic
snapshot containing state/events/artifacts. `GitHubStateBranchStore`: independent
`automation/dev-state`, immutable artifacts/events and parent-bound non-force ref
update. Conflicting writers fail before external delivery. No blind mutation retry.
Initial state creation uses an independent root commit, not a product HEAD change.
The bootstrap store must be empty; any existing revision/work item rejects a second
attempt. Current delivery does not initialize the state branch.

`DeploymentSetup` is an immutable aggregate member. `validate_append` prevents replacement
or removal once written. The setup event independently records version/fingerprint,
principal presence, mode, bridge, merge, Ready, actor and time without any token/secret.

## 6. State Machine

The transition table covers PLANNED through CLOSED plus waiting, recoverable, blocked and
Chairman-decision states. Guards enforce role, ordering, exact input SHA and evidence.
CI reruns revoke cached eligibility. HEAD changes clear approval and CI, requiring a
new review. RECOVERABLE_FAILURE retains the safe prior stage for CI, authenticated
engineering and read-only reconciliation failures. New HEAD, fresh CI/reconciliation,
or engineer retry resumes with zero Chairman events. Unknown side effects remain sticky.
See [state machine](docs/dev-governance/STATE_MACHINE.md).

After bootstrap CLOSED, protected setup is an administrative transition rather than an
Architecture Approval. Once the external kill switch is later enabled, an authenticated
Architect with the recorded standard-work delegation can register the first approved
ordinary item; separate publication moves it from PLANNED to SPEC_READY.

## 7. Workflow Events

Versioned events record identity, work item, timestamp, input SHA, actor, metadata
and output state. Supported events include SPEC/FIX publication, engineering,
architecture review, CI, Ready/merge/closeout, budgets, incidents, memory updates
and pause/recovery. GitHub workflows serialize reconciliation; critical event
commands require authenticated role mapping rather than an actor in PR text.
`DEPLOYMENT_SETUP_COMPLETED` is written only by the protected one-time setup entry point;
it is not accepted as a normal event command.

## 8. Artifact Protocol

SPEC is hash-pinned at registration. REVIEW, changed text modules, relevant ADRs
and required memory are validated before a review request. Architecture output is
typed JSON plus immutable Markdown; FIX responses become scoped, durable artifacts.
Task reservation and subsequent delivery records are separate immutable artifacts.
See [artifact protocol](docs/dev-governance/ARTIFACT_PROTOCOL.md).

The `.github/dev-governance/work-item.json` descriptor is bootstrap-only and never
changes per future SPEC. Ordinary work resolves exactly one PR number/branch candidate
from durable state, then checks exact HEAD, SPEC hash and REVIEW path. No match,
partial mismatch or multiple candidates fails closed.

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
After bootstrap, the context command loads the state branch and uses its resolved
WorkItem/artifacts; it no longer depends on a per-PR descriptor edit.

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

When the state branch exists, PR identity comes solely from exactly one registered
WorkItem. The static descriptor is read only for this initial DEV-GOV bootstrap PR.

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

The deployment setup schema deliberately excludes AUTO and fixes `auto_ready=false`.
Recording a MANUAL/DRY_RUN policy does not activate it; the repository kill switch is
still OFF for this PR. Any future AUTO policy needs a new reviewed governance change.

## 18. Chairman Gate

Master Requirement, investment/risk permissions, live broker/leverage, core
architecture and governance/security changes require Chairman intervention.
Classification examines real changed paths, not just author-supplied labels.
Positive tests retain escalation for governance/security configuration, broker,
leverage, live trading, portfolio policy and explicit risk hard-cap/limit surfaces.
Negative tests prove ordinary risk implementation, test and documentation filenames
do not automatically claim a hard-cap relaxation.
Pause, disable-auto-merge and recovery are separately authenticated. A protected
delegation can authorize a standard future work item; no such delegation is present
in the inactive repository defaults, and model-generated text cannot supply it. A protected
post-merge setup may record an explicit Chairman-reviewed standard-work delegation, but
the setup actor cannot overlap Architect/Engineer/bot and the Architect still authenticates
ordinary registration independently.

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
Known bridge-unavailable delivery is explicitly recorded before retry; retry task
artifacts append rather than overwrite. The runner has a bounded eight-tick invocation,
not an infinite agent conversation.

## 24. Failure Modes

Covered failures include GitHub unavailable/403, stale SHA/CI, missing artifacts,
malformed/refused API results, branch drift, tree mismatch, store conflict, crash,
permission denial, budget exhaustion and unexpected PR closure.

Recoverable: CI test/lint/type/build failure, known engineering failure, known
pre-delivery bridge unavailability, transient bounded GitHub read failure and stale CI
superseded by a new exact-head run. These never grant eligibility and need no Chairman.
Sticky: premature merge/exception, authority/security violation, Chairman Gate,
budget/review-loop exhaustion, and unknown mutation/paid-call outcome. These block or
escalate. Failures while requesting a successor do
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

Setup accepts only protected Environment values, validates complete role maps and
MANUAL/DRY_RUN constraints, and stores non-secret policy only. Fingerprint verification
makes restart deterministic. Mutable config privileges, fingerprint drift, duplicate setup,
wrong actor, missing authority, setup while active, AUTO/Ready and recognized secret
material all fail closed.

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
Deployment audit includes the formal bootstrap evidence already in state plus setup actor,
timestamp, complete policy/version/fingerprint and a separate completion event.

## 29. Technical Debt Registry

Runtime non-blocking review items append structured debt records with origin,
severity, blocking status, target phase and status. Static deployment debt is in
`docs/project/TECHNICAL_DEBT.md`: main protection, protected deployment setup and external
bridge setup.
The existing GitHub Actions Node 20 declaration warning is recorded as low maintenance debt.
These are implementation-reported activation limitations; their classification
does not pre-empt the Architect's decision on this PR.

## 30. Memory Recovery

Restart tests construct a fresh orchestrator using only persisted state plus
repository evidence. Approval, SHA, CI, budgets, events, task/result artifacts and
debt remain available. Stored API results can be ingested after a crash without a
second paid call. Unknown reservations are not automatically redelivered. See
[disaster recovery](docs/dev-governance/DISASTER_RECOVERY.md).
Transient GitHub read failure is also tested across two reconciliations: the first
persists RECOVERABLE_FAILURE; the later authenticated read/CI succeeds and restores
the safe stage with no Chairman event.

Deployment restart re-materializes only the immutable effective policy in state, verifies
its canonical hash, and uses the repository variable strictly as a kill switch. It never
falls back to mutable privileged config.

## 31. Premature Merge Regression

Regression recreates candidate approval followed by an externally merged PR.
Expected outcome: BLOCKED, governance_exception=true, PR_MERGED_EARLY, paused
pipeline, no cleanup and no NEXT_SPEC. Tests also exercise approval invalidation
after HEAD drift and rejection of old-SHA review results.

The correction E2E adds HEAD A CI FAILED → no merge → engineer pushes HEAD B → old
approval/CI invalidated → HEAD B CI PASSED → new Architecture Review → FINAL_APPROVED
→ eligible. It asserts zero Chairman events. The existing premature-merge test remains
sticky and cannot use this operational recovery path.

## 32. Test Evidence

Local Python: 3.12.14, isolated `.venv`, editable `.[test]` installation.

```text
python -m pytest apps/backend/tests/dev_governance apps/backend/tests/architecture \
  --cov=aic_dev_governance --cov-branch --cov-report=json:tmp/dev-gov-fix002-coverage.json \
  --cov-fail-under=0 -q --tb=short
272 passed; dedicated governance package coverage 96.0164% statement+branch combined.

python -m pytest --ignore-glob='*postgresql*' \
  --ignore=apps/backend/tests/persistence/test_migrations.py -q --tb=short
818 passed (explicit non-database subset, NOT a full-suite claim)
```

The first local full-suite attempt could not supply PostgreSQL/AIC_DATABASE_URL
(10 failures and 30 setup errors for that environment); it also exposed one new
fixture identity error, which was corrected. Later audit refinement exposed an
attempt to overwrite an immutable task artifact; delivery is now appended separately.
No existing test was weakened or deleted. Full PostgreSQL validation remains mandatory
in the final-HEAD GitHub backend job, not replaced by the local subset.

E2E tests cover happy path, FIX/re-review at a new SHA, premature merge, repeated
review budget exhaustion, lost chat context/restart, concurrent dispatch, bootstrap
while disabled, one-shot rejection, state-based PR identity, CI correction without
Chairman and transient GitHub recovery. FIX-002 adds protected setup while OFF,
immutable policy/fingerprint, duplicate/unauthorized/secret/tamper rejection, exact
operator ordering, descriptor-independent Gate and synthetic first-item engineering
delivery with zero recovery/governance-bypass events.

## 33. Coverage

Local dedicated-suite statement-plus-branch targets are enforced by executable
`coverage_gate.verify_coverage`, not rounded display percentages:

| Module / requirement | Measured baseline | Required |
|---|---:|---:|
| Deployment setup/effective policy (`deployment.py`) | 100% | 100% |
| State machine | 100% | 95% |
| Merge gate, SHA lock and CI gate (`gates.py`) | 100% | 100% |
| Read-only state identity / SHA-CI gate (`ci_gate.py`) | 100% | 100% |
| AI budget | 100% | 95% |
| State store | 100% | 95% |
| GitHub adapter | 92.9825% | 90% |

The corrected critical percentages and complete package coverage are produced by
the final local run and independently enforced in exact-head CI. Whole-repository
coverage, including PostgreSQL paths, comes from
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

`python -m mypy`: passed, 141 source files under strict configuration. The new
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

A second protected manual workflow, `AIC Development Governance Bootstrap`, can run
post-merge while the normal pipeline remains disabled. It installs trusted main,
authenticates the actor against protected environment variable
`AIC_BOOTSTRAP_CHAIRMAN`, verifies the exact Architecture-reviewed head, merged/tree/
main-containment/CI/branch-deletion evidence, and creates only the initial state.

A third protected manual workflow, `AIC Development Governance Setup`, is available only
from trusted main after bootstrap. It shares the serialized state-writer concurrency group,
requires environment `aic-development-governance-setup`, validates protected Chairman and
non-secret policy variables, requires the normal repository switch OFF, and writes only
the one-time deployment record/event. It has no dispatch/approval/Ready/merge path. The
normal workflow separately receives repository variable `AIC_PIPELINE_ENABLED`; only when
later true can it materialize the stored fingerprinted policy.

This committed review precedes the commit SHA/CI run it describes. Final run ID,
attempt, head SHA, all four job conclusions and artifact identities are published
in the PR/final external attestation after CI completion. Pending CI is not approval.

## 38. Bootstrap Limitations

The initial PR receives a narrowly scoped read-only bootstrap check, bound to this
work item, branch, clean-main base and Draft state. It cannot approve or merge itself.
The independent state branch does not yet exist. One-time post-merge initialization
uses a protected environment actor independent of pre-existing policy principals.
It requires exact reviewed HEAD, actual merged/tree/current-main containment/CI,
deleted feature branch and external Architecture Closeout reference. It neither
requires nor enables `pipeline_enabled`; a second attempt is rejected.

This initial-state exception does not become an activation exception. Deployment Setup is
a second one-shot transition whose complete policy is immutable. It can run while the
normal pipeline is OFF, but only after bootstrap CLOSED; duplicate, changed, unauthorized
or already-active setup fails closed. Ordinary work then uses state identity and the normal
Gate. Tests prove a synthetic SPEC-010-like item reaches SPEC_READY and emits one engineering
task without direct state edits, descriptor edits, check bypass or Chairman recovery.

## 39. Chairman Setup Required

See [SETUP-DEV-GOV-001-CHAIRMAN.md](SETUP-DEV-GOV-001-CHAIRMAN.md) and
[branch protection checklist](docs/governance/BRANCH_PROTECTION_RECOMMENDATIONS.md).
Administrator must configure protection/no bypass/required checks. Chairman must
select identities, protected environment/token, escalation channel and optional
Work/API consumer. Paid model selection and execution delegation require explicit
decisions. These settings were not changed during implementation.

Bootstrap setup specifically requires protected environment
`aic-development-governance-bootstrap`, required reviewers and the reviewed
`AIC_BOOTSTRAP_CHAIRMAN` GitHub login. This is post-merge setup, not active now.

The executable sequence is: human merge; formal Closeout/feature cleanup; protected
bootstrap environment; bootstrap state; main protection; protected deployment environment;
one-time setup while OFF; ordinary Gate verification; MANUAL/DRY_RUN activation; first
approved registration; optional external bridge; and only later separate AUTO review.
Automated tests assert this ordering and that the setup workflow cannot run the normal loop.

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
- Protected bootstrap/setup environments, real identities, policy and the external switch
  remain post-merge administrator tasks; none is configured by this PR.
- GitHub currently forces Node 24 for actions declaring deprecated Node 20; all jobs
  pass, but action version upgrades remain a reviewed maintenance task.

## 41. Final HEAD Requirement

Final delivery must verify local HEAD == origin feature HEAD == PR headRefOid, an
open Draft PR targeting main, successful CI for that exact full SHA, clean workspace
and no Auto Merge request. Any code/doc follow-up changes HEAD and require fresh CI
and review. No evidence-only commit will be added merely to record its own SHA.
The final PR body/response and post-commit attestation supply the full immutable new
SHA, all check-run identities and artifact hashes. Embedding a commit's own SHA inside
that same commit is impossible; external attestation avoids an endless evidence-only loop.

### FIX-002 required evidence matrix

1. Post-bootstrap activation: protected Option B setup, immutable state policy, external
   activation kill switch.
2. One-time authority: protected Chairman actor plus absent prior `DeploymentSetup`.
3. No bypass: trusted-main workflow, formal closed bootstrap and main protection ordering;
   no direct-push/check-disable/state-edit operation.
4. Branch protection ordering: executable 12-step Chairman guide plus ordering regression.
5. Effective policy: schema-validated full non-secret record and canonical SHA-256
   version/fingerprint, verified again on every runtime materialization.
6. First work item: synthetic SPEC-010-like registration reaches SPEC_READY and emits a
   delivered engineering task with no recovery or governance exception.
7. Unauthorized setup: wrong/missing actor, invalid event and active pipeline are rejected.
8. Later sensitive policy: mutable privileged config and setup rewrite are rejected; setup
   workflow/config diffs remain Chairman-sensitive.
9. Exact new HEAD: supplied externally after the implementation commit; no evidence-only
   commit will move its own attested SHA.
10. Full PostgreSQL suite: required exact-HEAD `Backend tests` CI job; local result is
    explicitly only the 816-test non-database subset.
11. Coverage: local 272-test suite passes all executable targets, including 100% combined
    statement/branch for `deployment.py`; exact JSON is also a CI artifact.
12. Ruff: local all-repository check passes; exact-HEAD CI repeats it.
13. Strict mypy: local strict check passes for 141 source files; exact-HEAD CI repeats it.
14. WPF Release: no desktop change; required exact-HEAD Windows CI supplies the build.
15. Exact-head CI: supplied externally with run/check/artifact IDs after all jobs pass.
16. Pipeline: static config and repository state observed for this PR remain OFF.
17. Auto Merge: policy default and PR Auto Merge remain OFF.
18. State branch: `automation/dev-state` remains absent; setup/bootstrap were only tested
    against isolated stores.
19. SPEC-010: NOT STARTED; the test identity is explicitly `SYNTHETIC-SPEC-010`.

## 42. Final Recommendation

**B. APPROVED CANDIDATE WITH NON-BLOCKING DEBT**

Submit the corrected implementation and exact-HEAD evidence for Chief Investment
Architect re-review. Remaining debt is post-merge administrative setup/bridge/protection,
action-runtime maintenance and the documented remote cleanup race. This is a
Codex engineering candidate recommendation, not Architecture Final Approval.

Required stop: keep DEV-GOV-001 Draft/unmerged, Auto Merge OFF, SPEC-010 NOT STARTED;
wait for Chief Investment Architect review and subsequent Chairman manual action.
