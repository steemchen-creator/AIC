# Disaster Recovery

1. Disable AIC_PIPELINE_ENABLED and revoke/rotate the bot token if compromised.
2. Preserve automation/dev-state commit history and workflow/PR evidence.
3. Read a consistent state snapshot at a pinned ref, immutable events/reviews,
   project memory, approved artifacts, actual PR/head and exact CI.
4. Compare snapshot revision, work item, head, architecture status, unresolved FIX,
   budget reservations and merge state. Run read-only status/metrics first.
5. Resume only after authorized reconciliation; no automatic state/history rollback.

Local store writes one envelope through fsync + atomic replace under an exclusive
lock. A stale lock after a process crash blocks new writers; verify no writer is
alive, preserve the old snapshot and remove only that exact lock before retry.
GitHub state commits append event and current.json in one tree; non-force parent-bound
ref updates reject concurrent siblings. No implementation HEAD changes.

RESERVED external tasks mean delivery may be unknown. Inspect provider/GitHub evidence;
do not replay a potentially paid model call. WAITING means the bridge refused before
calling and may resume after explicit bridge authorization. Known CI/engineering/read
failures use RECOVERABLE_FAILURE and retain a safe resume stage; authenticated retry,
new HEAD or later reconciliation needs no Chairman. Unknown side-effect outcomes remain
sticky and require explicit recovery authority.

Premature merge is a governance incident: block pipeline, retain the actual merged
facts and escalate. Do not automatically revert/re-merge, label it ordinary closeout
or generate the next SPEC. A separate governance exception task is required.

Bootstrap initialization is a one-time Chairman import through the separate protected
manual bootstrap workflow while all activation flags remain OFF, after DEV-GOV-001 has been
manually merged, externally closed out, its branch deleted and exact CI verified.
It verifies the reviewed head, merged PR/tree, merge containment in current main,
branch deletion, exact CI and records the external closeout reference, never
creates the bootstrap approval itself and never requests SPEC-010.

Deployment setup is a second one-time transition after bootstrap and before activation.
Recovery must read the complete stored `DeploymentSetup`, recompute the canonical policy
fingerprint, revalidate actor/role separation and policy mode, and compare it with the
immutable setup event and protected workflow evidence. A missing/mismatched fingerprint,
changed record, duplicate setup, or privileged value committed in mutable static config
stops recovery. Never reconstruct identities from PR prose or manually edit state.

To contain an incident, keep repository variable `AIC_PIPELINE_ENABLED=false`; this leaves
the audited policy intact but prevents external effects. Restore the external switch only
after state/fingerprint/protection/bridge checks succeed. Setup itself cannot be rerun to
rotate policy; policy rotation needs a separately reviewed governance design/change.

## Sensitive-diff revalidation

DEV-GOV-RECOVERY-002 handles a stale `SENSITIVE_DIFF:*` latch after the sensitive change
has been completely removed from the current PR diff. It cannot authorize a still-sensitive
change. `RECOVERY_AUTHORIZED` retains its original restrictions and is not a substitute.

1. Preserve the historical escalation and inspect current PR/state identity and other
   incidents. A clean diff alone does not authorize removal of the latch.
2. After this recovery implementation has been independently reviewed and published on
   main, the configured Chairman uses **AIC Development Orchestrator**, on **main**, with
   command **event** and the exact payload below. Re-read the actual HEAD before dispatch;
   the example is the SPEC-010 HEAD at recovery-task authorization, not a mutable alias.
3. Trusted-main code fetches the PR and current diff itself. It verifies PR identity
   (registered PR number, target branch, repository, main base, open
   status, exact HEAD), classifies the changed paths, then rereads the PR to detect drift.
   Both old and new paths of renames are classified. The adapter rejects results at the
   [GitHub PR-files API ceiling](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files)
   of 3,000 files, because completeness cannot be established from that response.
4. Verify the new append-only `SENSITIVE_DIFF_REVALIDATED` event and its actor, HEAD,
   base SHA, PR number and path digest. No historical event or approval is rewritten.
5. For SPEC-010's `RECOVERABLE_FAILURE`, confirm that `CI_FAILED`, recovery stage and
   failed CI snapshot remain intact. Re-run the failed exact-HEAD CI checks and let ordinary
   reconciliation process fresh results. Then continue independent Architecture Review.

```json
{
  "work_item_id": "SPEC-010",
  "event_type": "SENSITIVE_DIFF_REVALIDATED",
  "head_sha": "99756090eeb267d79e33dc8789a00b395ec8f713"
}
```

The three fields above are required; metadata, changed-path claims, PR-number overrides
and actor claims are rejected. GitHub's authenticated workflow actor provides authority.
The reducer additionally requires repository evidence supplied outside event metadata.

Recovery fails closed for a stale HEAD, identity drift, unavailable/incomplete GitHub
evidence, any current sensitive area, missing historical escalation evidence, unrelated
blockers, other Chairman causes, budget incidents, governance exceptions or merge evidence.
Mixed incidents reject the entire request and preserve every blocker; no broad reset occurs.
A pure solely sensitive `CHAIRMAN_DECISION_REQUIRED` may return to `REVIEW_REQUIRED` or
`FIXING`. Neither path marks Ready, approves or merges. Existing workflow permissions,
protected environment and Governance Gate remain authoritative.

Do not run feature-branch recovery code against live state, edit `automation/dev-state`,
or replace the Chairman with an engineering principal. This task implements the mechanism;
deployment and Chairman invocation are separate operations after review/publication.
