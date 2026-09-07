# Merge and Closeout Gate

## Eligibility

All conditions are ANDed: enabled/unpaused/healthy work item; FINAL_APPROVED;
approved SHA = PR HEAD = CI HEAD; every configured and discovered required check
succeeds at that SHA; trusted check App identity; open non-Draft same-repository
main-target PR; matching branch/number; no unresolved FIX, governance exception,
Chairman requirement or exhausted budget; predecessor CLOSED.

Defaults: Governance baseline, Backend tests, Desktop build,
AIC Development Governance Gate. Effective main rules and branch protection may add
checks. Discovery failure, absent app-bound evidence or unknown status blocks merge.
A legacy status without verifiable check-app identity is not silently trusted.

## Execution

Eligibility is not merge authorization. MANUAL records the gate for a human;
DRY_RUN records eligibility without merging; AUTO also requires explicit
merge_enabled and no kill switch. DEV-GOV-001 is permanently bootstrap-manual-only.
Automatic Ready is configurable and requires final approval plus exact SHA/CI.
HEAD change invalidates approval and restores Draft.

Merge uses GitHub squash with expected SHA. There is no force option, automatic
fallback method, implicit approval inheritance or retry of ambiguous mutation.

## Closeout

Verify actual merged PR/head/merge commit, compare approved head tree to merge tree,
fetch/fast-forward clean local main, verify main contains merge, validate branch head,
delete local ref conditionally with its expected old SHA, then remove/verify remote
feature ref. Record tree/main/CI/deletion/clean evidence externally, mark CLOSED and
emit NEXT_SPEC_REQUESTED only while project healthy and no Chairman gate.

Tree mismatch (including legitimate concurrent-base changes) needs review; V1 never
guesses semantic equivalence. Remote REST branch deletion has no expected-SHA field:
single-writer branch ownership and protected deployment credentials are required;
a changed ref detected before deletion blocks cleanup. No unrelated branch is touched.
