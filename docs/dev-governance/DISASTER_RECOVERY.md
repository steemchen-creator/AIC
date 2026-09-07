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
