# FIX-DEV-GOV-001-001 — Bootstrap, Work-Item Identity & Recoverable Failure Corrections

**Project:** AIC — AI Investment Committee
**Parent:** DEV-GOV-001 — AIC Autonomous Development Pipeline V1.0
**Review target HEAD:** `78415e7af9609e1f40019436d4870d9bf7b4467d`
**Architecture result:** `CHANGES_REQUIRED`
**Authority:** Chief Investment Architect Architecture Review
**Merge status:** NOT AUTHORIZED
**SPEC-010:** NOT AUTHORIZED TO START

---

# 0. Execution authorization

Explicitly authorize Codex to implement only the corrections in this FIX on the existing:

`feature/dev-gov-001-autonomous-development-pipeline`

Keep PR #12 Draft/Open/Not Merged.

After changes:

1. update implementation and tests;
2. update `REVIEW-DEV-GOV-001.md`;
3. commit and push;
4. wait for exact new HEAD CI;
5. produce a new Final HEAD / CI Attestation;
6. stop for Chief Investment Architect re-review.

Do not merge PR #12.
Do not enable the pipeline.
Do not enable Auto Merge.
Do not initialize `automation/dev-state`.
Do not start SPEC-010.

---

# 1. BLOCKER A — Bootstrap initialization currently has a configuration/state deadlock

## Problem

The submitted bootstrap correctly ships with all activation switches OFF and privileged principal lists empty.

However, the current runtime entry point exits when `policy.pipeline_enabled == false` before a `workflow_dispatch initialize` operation can run. `initialize_state()` also requires a Chairman principal to already exist in trusted policy.

That creates a bootstrap cycle:

```text
DEV-GOV merged
→ pipeline_enabled=false / Chairman principals empty
→ initialize cannot run

To make initialize runnable:
→ a config PR must first change trusted policy

But before initialization:
→ automation/dev-state does not exist
→ the normal Governance Gate cannot validate an ordinary setup PR
```

The documented setup path must not require direct-pushing main, bypassing a failed required check, or applying an untracked local mutation.

## Required correction

Provide an explicit **bootstrap-only initialization path** that works while normal autonomous orchestration remains disabled.

It must:

- be separate from normal autonomous orchestration;
- be callable only through a protected/manual GitHub workflow;
- not require `pipeline_enabled=true`;
- not enable engineering, Architecture Review, Ready or Merge effects;
- authenticate bootstrap Chairman authority through a trusted mechanism that does not depend on a prior runtime-state/config PR;
- verify actual GitHub evidence before creating state;
- create only the initial `automation/dev-state`;
- be one-shot, idempotent/fail-closed.

A protected GitHub Environment variable / reviewed bootstrap configuration is acceptable. Do not infer Chairman authority from PR text, issue comments or model output.

## Mandatory bootstrap verification

Before state creation, verify at least:

```text
DEV-GOV PR is MERGED
actual PR head == reviewed/approved bootstrap head referenced by Architecture Closeout
merge commit exists
feature tree == merge tree
merge commit is contained by current main
exact-head CI passed
feature branch is deleted
Architecture Closeout reference is non-empty
state branch does not already exist
```

Do not require current main to equal the merge commit if a later legitimate main commit exists; ancestry/containment is the safer invariant.

## Acceptance test

Add E2E proving:

```text
policy.pipeline_enabled = false
normal autonomous side effects = disabled
bootstrap initialize = allowed through bootstrap-only authority
state branch is created
DEV-GOV is imported CLOSED
no NEXT_SPEC is emitted
no engineering/review/merge task is triggered
```

A second initialization attempt must be rejected.

---

# 2. BLOCKER B — Per-PR `.github/dev-governance/work-item.json` conflicts with Chairman Gate

## Problem

The Governance Gate reads `.github/dev-governance/work-item.json` from the PR checkout to identify the work item.

For a future SPEC PR, that descriptor must therefore change from DEV-GOV-001 to the new work item, or the gate will compare the future PR against the closed DEV-GOV state and reject it.

But the sensitive-path classifier treats `.github/` changes as `secret_permission_model`, which triggers `CHAIRMAN_DECISION_REQUIRED`.

That makes the ordinary path:

```text
Every new SPEC PR
→ update .github/dev-governance/work-item.json
→ .github change classified sensitive
→ Chairman escalation
```

This defeats the primary DEV-GOV goal.

## Required correction

After bootstrap, ordinary implementation PR identity must come from durable state, not from a mutable per-PR `.github` descriptor.

Recommended V1:

```text
GitHub PR number / branch / exact HEAD
        ↓
automation/dev-state
        ↓
resolve exactly one registered WorkItem
        ↓
validate target_branch / pr_number / head_sha / SPEC hash / REVIEW path / state
```

The existing `.github/dev-governance/work-item.json` may remain only as:

- a bootstrap-only descriptor; or
- a static control-plane schema/version descriptor that does not change per SPEC.

It must not be edited in every normal implementation PR.

## Mandatory tests

### Ordinary future SPEC

```text
DEV-GOV CLOSED
SPEC-010 registered and SPEC_READY
engineering creates feature/spec010...
PR attached
PR does NOT change .github/dev-governance/*
Governance Gate resolves SPEC-010 from state
no Chairman escalation
gate passes when evidence is valid
```

### Mismatch

Wrong branch/head/PR mapping must fail closed.

### Ambiguity

More than one candidate work item for a PR must fail closed.

---

# 3. BLOCKER C — Ordinary CI / transport failures become sticky Chairman-controlled blocks

## Problem

The reducer currently places `CI_FAILED`, `TASK_FAILED`, `OPERATION_FAILED` and similar operational failures into `BLOCKED`.

`PR_HEAD_CHANGED` is rejected while BLOCKED.

The explicit recovery path from BLOCKED is `RECOVERY_AUTHORIZED`, a Chairman event.

So a normal engineering sequence:

```text
Codex creates PR
→ CI fails
→ Codex fixes code
→ pushes new HEAD
```

cannot continue without Chairman recovery. A transient GitHub failure can also become a Chairman interruption.

That contradicts the intended role split: ordinary CI failures, code fixes and recoverable infrastructure failures must not require Chairman participation.

## Required correction

Separate failure classes.

### Sticky governance/authority failures

Examples:

```text
premature merge
governance exception
invalid authority
security-policy violation
Master Requirement conflict
Chairman Gate
AI budget/review-loop exhaustion
unknown/ambiguous paid model-call outcome where duplicate execution cannot be proven safe
```

These may remain BLOCKED / CHAIRMAN_DECISION_REQUIRED.

### Recoverable engineering/operational failures

Examples:

```text
CI test/lint/type/build failure
engineering implementation failure
known pre-delivery bridge unavailability
transient GitHub GET failure after bounded retries
stale CI replaced by a new exact-head run
```

Use explicit recoverable states/events or equivalent semantics.

Mandatory behavior:

- failed CI never grants merge eligibility;
- engineer may fix and push a new HEAD;
- new HEAD invalidates old CI/review evidence;
- fresh exact-head CI restores the normal review path;
- ordinary correction requires zero Chairman events;
- retry remains bounded;
- unknown side-effect outcomes remain fail-closed.

## Mandatory tests

E2E:

```text
HEAD A CI FAILED
→ no merge
→ engineer pushes HEAD B
→ old evidence invalidated
→ HEAD B CI PASSED
→ Architecture Review
→ FINAL_APPROVED
→ eligible
```

Assert Chairman intervention count is zero.

Transient GitHub read failure must also be able to recover on a later authenticated reconciliation without Chairman.

Keep a separate regression proving `PR_MERGED_EARLY` remains sticky and cannot auto-recover.

---

# 4. REQUIRED HARDENING — Chairman Gate path classification is too broad

The current classifier is deliberately conservative, but a generic `"risk"` filename substring can classify ordinary risk implementation/tests/docs as `platform_risk_hard_cap`.

Chairman intervention is required for actual hard-cap/permission relaxation, not every file whose path contains `risk`.

Refine deterministic classification so that:

- governance/security configuration surfaces remain protected;
- real-money/broker/leverage/live-trading permission changes remain protected;
- actual hard-cap policy/config surfaces remain protected;
- ordinary implementation/tests/docs with a risk-related filename do not automatically claim hard-cap relaxation.

Do not delegate this classification to PR prose or an LLM.

Add positive and negative tests.

---

# 5. Preserve already-correct controls

Do not weaken:

- SHA-bound Architecture Approval;
- HEAD drift invalidation;
- exact-head CI;
- expected-SHA squash merge;
- no force merge;
- state-branch CAS;
- immutable audit/artifacts;
- prompt/repository injection boundary;
- budget reservation before external calls;
- premature-merge governance exception;
- bootstrap manual merge;
- Auto Merge default OFF;
- branch protection requirement before activation;
- Chairman Gate for real money / broker / leverage / hard-cap relaxation / Master Requirement / core governance;
- no SPEC-010 before DEV-GOV formal closeout.

---

# 6. Non-blocking setup items remain post-merge prerequisites

Do not activate during this FIX:

- main Branch Protection / Required Checks;
- live ChatGPT Work consumer;
- live Codex engineering consumer;
- OPENAI_API_KEY / paid model;
- role/token mappings;
- Auto Merge;
- `automation/dev-state`.

The existing action-runtime deprecation warning may remain technical debt unless it becomes failing/security-relevant.

---

# 7. Updated review evidence required

Update `REVIEW-DEV-GOV-001.md` with explicit evidence for:

1. bootstrap deadlock correction;
2. bootstrap-only authority;
3. post-bootstrap state-based work-item resolution;
4. removal of per-SPEC `.github` descriptor dependency;
5. recoverable vs sticky failure taxonomy;
6. CI-failure-without-Chairman E2E;
7. transient GitHub recovery;
8. Chairman Gate positive/negative tests;
9. exact new HEAD;
10. full PostgreSQL suite;
11. critical coverage;
12. Ruff;
13. strict mypy;
14. WPF Release;
15. exact-head GitHub Actions;
16. all activation switches still OFF.

---

# 8. Final recommendation format

Codex may return only:

```text
A. APPROVED CANDIDATE
B. APPROVED CANDIDATE WITH NON-BLOCKING DEBT
C. CHANGES REQUIRED
```

Codex does not grant Architecture Final Approval.

---

# 9. Stop condition

```text
Local HEAD == origin feature HEAD == PR #12 HEAD
PR #12 = DRAFT / OPEN / NOT MERGED
exact new HEAD CI = PASSED
workspace = CLEAN
Auto Merge = OFF
pipeline activation = OFF
automation/dev-state = NOT INITIALIZED
SPEC-010 = NOT STARTED
```

Then stop and return the updated Review Package + Final HEAD / CI Attestation.
