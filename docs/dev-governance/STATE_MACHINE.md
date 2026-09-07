# Development State Machine

Schema version: 1.0. All enums and wire contracts live in models.py; unknown fields
and invalid identifiers/SHA/timestamps are rejected.

## Normal path

PLANNED → SPEC_READY → IMPLEMENTING → IMPLEMENTATION_COMPLETE → REVIEW_REQUIRED →
ARCHITECTURE_REVIEWING → FINAL_APPROVED → MERGE_ELIGIBLE → MERGING → MERGED →
CLOSEOUT → CLOSED.

## Post-bootstrap deployment transition

`DEV-GOV-001=CLOSED` is followed by a separate one-time administrative transition:

```text
bootstrap CLOSED + normal pipeline OFF
→ protected Chairman deployment setup
→ DEPLOYMENT_SETUP_COMPLETED
→ fingerprinted MANUAL/DRY_RUN policy available
→ external activation switch ON
→ Architect registers approved ordinary work item
→ PLANNED → SPEC_READY
```

Deployment setup is not a WorkItem approval state and grants no Architecture Approval.
It requires the closed bootstrap, exact configured Chairman identity, complete separated
principals and non-secret validated policy. State append rules make the record immutable;
a duplicate setup fails closed. Activation itself does not edit state or policy—it only
materializes the recorded policy after fingerprint verification.

Review failure: ARCHITECTURE_REVIEWING → CHANGES_REQUIRED → FIX_READY → FIXING →
REVIEW_REQUIRED. Candidate/debt-only review results are not Final Approval.

## Interruptions and authority

HEAD change clears approval, eligibility and CI, restores Draft where needed, and
requires review of the new SHA. CI, known engineering, and read-only reconciliation
failures enter RECOVERABLE_FAILURE with the prior safe stage recorded. A new HEAD or
fresh exact-head CI/read reconciliation clears that operational failure without a
Chairman event. An authenticated engineering retry resumes its recorded engineering
stage; retries remain event-driven and external calls remain budgeted/bounded.
Premature merge records GOVERNANCE_EXCEPTION, pauses the project, and never emits
normal Closeout/Next SPEC. Budget and sensitive diff paths escalate to Chairman.

Execution authorization, architect review and Chairman policy decisions use separate
allowlisted principals. PR prose/labels do not supply any role. Engineer/architect
principal overlap is rejected for reviews.

A Chairman may pause/resume/disable auto-merge. Resume does not clear an incident,
budget limit or item blocker. Chairman recovery remains limited to sticky blocked
items. Unknown mutation or paid-call outcomes, authority/security violations,
governance exceptions and budget exhaustion stay fail-closed. There is no force-merge
or rollback transition.

CLOSED is terminal for implementation. A failure while requesting its successor is
a project-level blocked/waiting reason; it does not reopen the closed predecessor.

## Events, ordering and concurrency

Events include unique ID, aware timestamp, work item, authenticated actor, input SHA,
output state and bounded structured metadata. Stale timestamps are rejected. Event
IDs are permanently idempotent; matching type/work/SHA within the configured window
is deduplicated in the same output stage. Legitimate later lifecycle rounds are not
silently treated as earlier deliveries. State writes require expected revision.

Registration records execution authorization first and publication separately. The
authenticated Architect may use the reviewed standard-work delegation; this does not
impersonate Chairman or Architecture Approval of the SPEC's investment substance.
