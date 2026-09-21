# REVIEW — DEV-GOV-RECOVERY-003

## What and why

DEV-GOV-RECOVERY-002 correctly reads GitHub's raw PR files list, but that list is merge-base
based. After PR #22 placed the same `docs/project/TECHNICAL_DEBT.md` blob on current `main`,
PR #19 still reported the path even though the exact PR HEAD and current main contained the
same blob. The durable sensitive-diff latch therefore could not be revalidated.

This narrowly scoped repair changes only `SENSITIVE_DIFF_REVALIDATED`. It does not modify
SPEC-010 product code, PR #19, investment behavior, merge controls, or SPEC-011.

## Architecture and trust boundary

- The Application-owned repository protocol now exposes immutable `blob_sha(path, ref)` evidence.
- The GitHub adapter resolves that evidence through the contents API at an exact 40-character
  commit SHA and accepts only a file with a valid 40-character blob SHA. A 404 is represented as
  missing; malformed or unreadable evidence fails closed.
- The orchestrator preserves the existing registered PR number, target branch, repository,
  open/main base and exact-HEAD checks. Caller-supplied path and identity claims remain rejected.
- Raw PR changed paths are still fetched from `/pulls/{number}/files`, including rename endpoints
  and the existing 3,000-file completeness guard.
- Only paths classified as sensitive are compared. A sensitive path is removed from the effective
  list only when both exact refs contain the same blob SHA. Non-sensitive paths are untouched.
- The PR and `main` ref are reread after evidence collection. Any identity/base/HEAD/main drift,
  missing path, unequal blob, or read failure prevents recovery without a state write.
- The pure reducer continues to receive only the effective changed paths and retains every
  RECOVERY-002 restriction on state, mixed incidents, authority and append-only history.

No new framework or general diff engine is introduced. The impact is limited to eliminating one
false-positive, merge-base-only sensitive path. The principal risk is stale external evidence;
the double-read and exact-SHA/blob contract deliberately fail closed against it.

## Audit evidence

A successful event records:

- PR number and exact PR HEAD;
- PR base SHA and captured current main SHA;
- canonical SHA-256 of both raw and effective changed-path lists;
- raw and effective path counts;
- canonical JSON mapping of every equalized sensitive path to its exact blob SHA.

The legacy `changed_paths_sha256` field remains as the raw-list digest for compatibility.

## Deterministic regression coverage

The focused recovery suite covers:

1. merge-base-only sensitive path with equal blobs succeeds;
2. unequal blobs retain `SENSITIVE_DIFF_STILL_PRESENT`;
3. path missing from PR HEAD or current main fails closed;
4. current main moving during validation fails closed;
5. PR HEAD, base SHA, number, branch, repository, base branch, or state drift fails closed;
6. multiple sensitive paths with only a subset equalized still block;
7. blob-read and malformed evidence failures;
8. exact-ref GitHub blob lookup and 404 behavior;
9. all pre-existing DEV-GOV-RECOVERY-002 cases.

Local validation on Python 3.12.10:

- focused recovery suite: `69 passed`;
- complete governance suite: `341 passed`, branch-aware coverage `96.28%`;
- all non-database backend tests: `917 passed`, branch-aware coverage `92.34%`;
- DEV-GOV critical coverage verifier: passed (`state_machine`, `gates`, `budget`, `store`,
  `ci_gate`, and `deployment` at 100%; GitHub above its required threshold);
- Ruff: passed;
- strict mypy: passed for 141 source files;
- WPF Release build: passed with 0 warnings and 0 errors;
- `git diff --check`: passed.

The local Docker daemon is unavailable, so the unchanged GitHub backend job supplies PostgreSQL
17 for migrations and the complete infrastructure suite. Final exact-HEAD CI results are reported
in the Draft PR and delivery evidence after the immutable commit is pushed. No evidence-only commit
is required.

## Rollback

Rollback is the normal reviewed PR revert. No database migration, dependency, workflow permission,
state schema, or live governance state is changed. Existing `SENSITIVE_DIFF_REVALIDATED` events
remain readable because the event taxonomy is unchanged.
