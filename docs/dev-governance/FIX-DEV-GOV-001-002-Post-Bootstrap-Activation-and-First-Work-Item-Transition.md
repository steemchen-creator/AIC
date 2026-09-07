# FIX-DEV-GOV-001-002 — Post-Bootstrap Activation & First-Work-Item Transition

**Project:** AIC — AI Investment Committee
**Parent:** DEV-GOV-001 — AIC Autonomous Development Pipeline V1.0
**Previous FIX:** FIX-DEV-GOV-001-001
**Review target HEAD:** `a38316682e0edb95f2ebe38052d090e0fbf57a3b`
**Architecture result:** `CHANGES_REQUIRED`
**Authority:** Chief Investment Architect Architecture Review
**PR:** #12 must remain Draft / Open / Not Merged
**SPEC-010:** NOT AUTHORIZED TO START

---

# 0. Execution authorization

Explicitly authorize Codex to implement only this FIX on the existing:

`feature/dev-gov-001-autonomous-development-pipeline`

Do not merge PR #12.
Do not enable the live pipeline.
Do not enable Auto Merge.
Do not initialize `automation/dev-state`.
Do not start SPEC-010.

After implementation:

1. update tests and documentation;
2. update `REVIEW-DEV-GOV-001.md`;
3. commit and push;
4. wait for exact new HEAD CI;
5. provide Final HEAD / CI Attestation;
6. stop for Chief Investment Architect re-review.

---

# 1. BLOCKER — The post-bootstrap activation path is still circular

FIX-001 correctly solved the **initial state bootstrap** deadlock.

The new bootstrap can create:

```text
automation/dev-state
DEV-GOV-001 = CLOSED
```

while the normal pipeline remains disabled.

However, after that point the system still lacks a clean, governed path from:

```text
STATE INITIALIZED
+
pipeline_enabled = false
+
principals empty
+
normal orchestrator disabled
```

to:

```text
trusted identities configured
+
deployment policy configured
+
MANUAL / DRY_RUN pipeline usable
+
first ordinary work item can be registered
```

without bypassing the Governance Gate.

## Why this is a real deadlock

The delivered trusted config still contains:

```text
pipeline_enabled = false
principals[CHAIRMAN] = []
principals[ARCHITECT] = []
principals[ENGINEER] = []
standard_work_execution_authorization = null
```

The normal runner exits while `pipeline_enabled == false`.

Therefore a normal `workflow_dispatch register` cannot run yet.

But to enable/configure the system through a normal PR, that PR must pass:

```text
AIC Development Governance Gate
```

After bootstrap, the state branch is non-empty, so the Gate resolves PR identity only from a registered WorkItem.

The setup/config PR is not registered, because the normal registration path is still disabled.

Result:

```text
Need setup PR to enable/configure pipeline
→ setup PR needs registered state identity to pass the Gate
→ registration needs enabled/configured pipeline
→ circular dependency
```

The solution must not be:

- direct push to `main`;
- merge a failing required check;
- temporarily bypass branch protection;
- manually edit `automation/dev-state`;
- disable the Governance Gate;
- silently treat Chairman action as Architecture Approval.

---

# 2. Required outcome

Implement and test a **one-time governed Deployment Setup / Activation transition** that bridges:

```text
DEV-GOV bootstrap CLOSED
        ↓
protected one-time setup authority
        ↓
identities + deployment policy configured
        ↓
MANUAL or DRY_RUN operational state
        ↓
first ordinary work item can be registered
```

The normal autonomous pipeline must not be required to already be active in order to configure itself.

---

# 3. Allowed architecture choices

Codex may choose the cleanest design, but it must satisfy the acceptance criteria.

Acceptable patterns include:

## Option A — Protected one-time setup work item

A dedicated protected manual workflow can register/authorize exactly one:

```text
DEV-GOV-SETUP-001
```

while normal automation is disabled.

That work item then allows a normal reviewed setup PR to pass the Governance Gate.

The setup PR may configure:

- role principals;
- MANUAL / DRY_RUN mode;
- protected execution delegation;
- bridge selection;
- non-secret policy values.

After human review/merge and setup closeout, the bootstrap exception expires.

## Option B — Protected deployment policy outside mutable product PRs

Keep repository config as safe structural defaults and load privileged deployment values from a protected GitHub Environment / repository configuration.

If this approach is chosen:

- values must be schema-validated;
- protected identities must be explicit;
- secrets stay secrets;
- non-secret policy must have an auditable fingerprint/version in state;
- policy changes must trigger Chairman/Governance controls;
- normal PR text/model output cannot alter effective policy;
- restart/recovery must reproduce the same effective policy.

## Option C — Equivalent design

Any equivalent design is acceptable only if it proves the full transition without a governance bypass.

---

# 4. Mandatory security/authority rules

The setup path must preserve:

```text
EXECUTION_AUTHORIZATION
!=
ARCHITECTURE_APPROVAL
!=
CHAIRMAN_APPROVAL
```

The one-time setup authority may authorize configuration/deployment, but it may not:

- self-approve DEV-GOV implementation;
- approve a future investment SPEC;
- enable real money;
- enable leverage;
- bypass exact-head CI;
- bypass branch protection;
- grant Codex Architecture authority.

Protected setup must use a distinct authenticated Chairman/admin identity.

---

# 5. Required first-work-item behavior

After setup completes, prove that the first normal work item can be created without hacks.

At minimum:

```text
DEV-GOV-001 = CLOSED
deployment setup = COMPLETE
pipeline = MANUAL or DRY_RUN
SPEC-010 artifact exists as an approved/authorized input
```

Then:

```text
register SPEC-010
→ SPEC_READY
→ engineering task can be emitted
```

without:

- direct state edits;
- direct main push;
- changing bootstrap descriptor;
- disabling required checks;
- Chairman recovery because of ordinary registration mechanics.

**This test does not authorize actual SPEC-010 development during DEV-GOV implementation.**
Use a synthetic fixture work item in automated tests.

---

# 6. Required branch-protection ordering

Document and test a valid ordering that allows branch protection to be enabled without trapping the system.

The final setup guide must state the exact sequence.

For example:

```text
1. Human merge DEV-GOV
2. Formal Closeout / delete feature branch
3. Configure protected bootstrap environment
4. Bootstrap state
5. Configure/apply main protection
6. Run protected one-time deployment setup
7. Verify Governance Gate
8. Enable MANUAL or DRY_RUN
9. Register first normal work item
10. Only later, separately authorize AUTO
```

If your architecture requires a different sequence, prove it cannot require bypassing a required check.

---

# 7. Required state/audit evidence

The transition must leave durable evidence for:

```text
bootstrap completed
deployment setup authorized by
effective policy version/fingerprint
principals configured
mode selected
bridge mode selected
merge enabled/disabled
auto-ready enabled/disabled
setup timestamp
setup completed
```

Do not store tokens/secrets in state.

---

# 8. Required tests

Add E2E coverage for the complete lifecycle:

## 8.1 Bootstrap → Setup → First work item

```text
normal pipeline OFF
→ protected bootstrap initializes state
→ protected setup runs while normal pipeline is still OFF
→ setup becomes complete
→ MANUAL/DRY_RUN policy becomes usable
→ synthetic SPEC-010-like item registers
→ SPEC_READY
```

Zero governance bypasses.

## 8.2 Setup is one-time / controlled

A duplicate bootstrap or duplicate one-time setup must fail closed or be idempotently recognized.

## 8.3 Unauthorized setup

Wrong GitHub actor / missing protected environment authority:

```text
→ setup rejected
```

## 8.4 Ordinary PR Gate after setup

A synthetic ordinary PR:

```text
registered work item
correct branch / PR / HEAD / SPEC hash
→ Governance Gate passes
```

without modifying `.github/dev-governance/work-item.json`.

## 8.5 Sensitive policy change later

After setup, a later attempt to change privileged deployment/governance policy must again require Chairman/Governance authorization.

The one-time bootstrap/setup exception must not become a permanent bypass.

---

# 9. Documentation updates

Update at least:

```text
SETUP-DEV-GOV-001-CHAIRMAN.md
docs/dev-governance/OVERVIEW.md
docs/dev-governance/STATE_MACHINE.md
docs/dev-governance/SECURITY.md
docs/dev-governance/DISASTER_RECOVERY.md
REVIEW-DEV-GOV-001.md
```

The Chairman setup document must become executable as a real sequence, not only a checklist.

It must explicitly tell the user:

- what GitHub setting to configure;
- what is automatic;
- what is one-time;
- when branch protection is applied;
- when the state branch is created;
- when MANUAL / DRY_RUN can be enabled;
- when the external ChatGPT/Codex bridge is connected;
- when AUTO Merge may be considered.

---

# 10. Preserve all FIX-001 corrections

Do not regress:

- protected bootstrap while normal pipeline OFF;
- current-main containment instead of equality;
- state-based ordinary PR identity;
- bootstrap-only descriptor;
- recoverable CI/engineering/read failures;
- sticky governance exception;
- narrowed risk hard-cap classification;
- exact-SHA Architecture Approval;
- HEAD drift invalidation;
- exact-head CI;
- expected-SHA squash;
- immutable state/audit;
- AI Budget Guard;
- prompt-injection boundary;
- Auto Merge default OFF.

---

# 11. Current non-blocking deployment debt

These may remain post-merge setup items if the code path is complete and tested:

- actual GitHub Branch Protection is not yet configured;
- actual live ChatGPT Work/API bridge is not yet authorized;
- actual external Codex consumer is not yet authorized;
- real secrets/tokens are not yet installed;
- Node action runtime maintenance warning;
- documented narrow remote branch read/delete race.

But **the governed path to configure/activate them must exist without circular dependency.**

---

# 12. Final evidence required

Updated Review Package must explicitly show:

1. post-bootstrap activation design;
2. one-time setup authority;
3. no direct-push / check-bypass path;
4. branch-protection ordering;
5. effective policy audit/fingerprint;
6. synthetic first-work-item registration E2E;
7. unauthorized setup rejection;
8. later sensitive-policy escalation;
9. exact new HEAD;
10. full PostgreSQL suite;
11. coverage targets;
12. Ruff;
13. strict mypy;
14. WPF Release;
15. exact-head CI;
16. Pipeline still OFF for this PR;
17. Auto Merge still OFF;
18. state branch still NOT initialized;
19. SPEC-010 still NOT STARTED.

---

# 13. Final recommendation format

Codex may return only:

```text
A. APPROVED CANDIDATE
B. APPROVED CANDIDATE WITH NON-BLOCKING DEBT
C. CHANGES REQUIRED
```

Final Architecture Approval remains with the Chief Investment Architect.

---

# 14. Stop condition

After implementing this FIX:

```text
Local HEAD == origin feature HEAD == PR #12 HEAD
PR #12 = DRAFT / OPEN / NOT MERGED
exact new HEAD CI = PASSED
workspace = CLEAN
Pipeline = OFF
Auto Merge = OFF
automation/dev-state = NOT INITIALIZED
SPEC-010 = NOT STARTED
```

Then stop and return the updated Review Package + exact Final HEAD / CI Attestation.
