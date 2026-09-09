# SPEC-010: CHANGES_REQUIRED

Reviewed HEAD: `ae12e925fb5094e4274c9140a306325cd10a5334`

```json
{
  "work_item": "SPEC-010",
  "review_id": "SPEC010-ARCH-CHG-1",
  "result": "CHANGES_REQUIRED",
  "reviewed_head_sha": "ae12e925fb5094e4274c9140a306325cd10a5334",
  "blocking_items": [
    "BLOCKER-01: Bind every directive-producing path only to a Trade Plan revision visible at as_of; reject future revisions. Thesis invalidation must be atomic and must not leave a persisted directive if terminal transition fails.",
    "BLOCKER-02: Enforce authoritative position semantics: ENTRY requires zero position, SCALE_IN requires existing position, REDUCE must remain strictly partial, EXIT closes remaining position. Prevent repeated automatic stop/target directives for the same unresolved or consumed trigger.",
    "BLOCKER-03: Eliminate PostgreSQL aggregate lost updates by row locking or compare-and-swap/version enforcement. Concurrent revision/directive/execution appenders must never silently overwrite recovery_projection.",
    "BLOCKER-04: Do not finalize immutable outcome/adherence while an EXPIRED or INVALIDATED plan still has unresolved executable EXIT evidence. Pending execution must resolve before final outcome or use equivalent deterministic settlement semantics.",
    "BLOCKER-05: Freeze instrument identity for the entire lifetime of a plan_id, including DRAFT. Draft horizon/style/thesis/policies may remain editable as authorized."
  ],
  "non_blocking_items": [],
  "reviewed_at": "2026-09-09T16:16:06Z",
  "reviewer_role": "CHIEF_INVESTMENT_ARCHITECT"
}
```
