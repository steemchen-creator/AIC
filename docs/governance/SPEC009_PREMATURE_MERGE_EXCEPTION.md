# SPEC-009 Premature Merge Governance Exception and Closeout

## Record identity and authority

| Field | Value |
|---|---|
| exception_id | `FIX-SPEC009-002` |
| spec | `SPEC-009` |
| pr_number | [#10](https://github.com/steemchen-creator/AIC/pull/10) |
| feature_head | `e9c641d5ccd765f5dcc6cab03b672820561eb887` |
| merge_commit | `45f5791f98d3cb5cffbdaa960066aefa2be6bae9` |
| occurred_at | `2026-09-06T15:28:48Z` / `2026-09-06 23:28:48 +08:00` |
| classification | `GOVERNANCE_PROCESS_DEVIATION` |
| approved_by | Project owner through the explicit `FIX-SPEC009-002` execution authorization and its conditional closeout instruction. No separate Architecture Review sign-off is asserted. |
| architecture_review_reference | Owner-provided `FIX-SPEC009-002-Post-Merge-Governance-Exception-and-Closeout.md`, preceding `FIX-SPEC009-001-Final-HEAD-Draft-PR-CI-Attestation.md`, and [REVIEW-SPEC009](../../REVIEW-SPEC009.md). This remediation record is submitted for Architecture Review. |
| status | `RECORDED`; conditional SPEC-009 closeout and branch-cleanup verification are described below. |

This record preserves **PROCESS DEVIATION OCCURRED**. Successful technical
verification does not make the original merge process compliant. The incident is
not classified as `FUNCTIONAL_DEFECT`, `ARCHITECTURE_DEFECT`, or `DATA_DEFECT`.

## What happened and rule violated

PR #10, `feat(etf): add domestic ETF and index exposure foundation`, was squash
merged before the Final Attestation / Architecture Final Approval gate was
completed. GitHub reports `merged = true`, `draft = false`, and `state = closed`
with the merge commit and timestamp above. It cannot retrospectively satisfy
`DRAFT / OPEN / NOT MERGED`.

The violated rule was: **do not merge before Architecture Review / Final
Attestation is complete**. `REVIEW-SPEC009.md` sections 54, 57, and 58 require the
final head evidence and prohibit Ready/Merge before Architecture Review.
`AGENTS.md` also requires review and checks before a human merge and prohibits
AI self-merge. This record does not attribute the merge to an actor or infer
intent beyond the verified timeline.

## Tree equivalence and why code rollback was not required

Git object verification returned:

```text
Feature HEAD: e9c641d5ccd765f5dcc6cab03b672820561eb887
Feature tree: 053af5903a1013c74e7115d887c734e7093d6a5a
Merge commit: 45f5791f98d3cb5cffbdaa960066aefa2be6bae9
Merge tree:   053af5903a1013c74e7115d887c734e7093d6a5a
Feature tree == Merge tree: YES
Content diff: NONE
```

Commands executed against the local Git objects fetched from `origin`:

```text
git rev-parse e9c641d5ccd765f5dcc6cab03b672820561eb887^{tree}
git rev-parse 45f5791f98d3cb5cffbdaa960066aefa2be6bae9^{tree}
git diff e9c641d5ccd765f5dcc6cab03b672820561eb887 45f5791f98d3cb5cffbdaa960066aefa2be6bae9 --stat
git diff e9c641d5ccd765f5dcc6cab03b672820561eb887 45f5791f98d3cb5cffbdaa960066aefa2be6bae9
```

Both diff commands returned no content. The checked merge tree is identical to
the tested feature tree. Exact feature-head CI and a fresh regression of the
merged main commit also passed. No technical evidence requires a code rollback;
revert/remerge would not erase the process deviation. No revert, remerge,
replacement implementation PR, or history rewrite is part of this remediation.

## Exact feature-head CI evidence

[CI run 34024959355, attempt 1](https://github.com/steemchen-creator/AIC/actions/runs/34024959355/attempts/1)
reports `head_sha = e9c641d5ccd765f5dcc6cab03b672820561eb887` and
`conclusion = success`. The individual jobs report the same `head_sha`.

| Check | Conclusion |
|---|---|
| Governance baseline | PASSED |
| Backend tests | PASSED |
| Desktop build | PASSED |
| Additional required checks | NONE configured at verification |

GitHub's required-status-checks endpoint reports `Branch not protected`; the
effective rules endpoint for `main` returns an empty list. These observations
do not waive the three task-mandated checks or the human review requirement.

## Latest main and fresh regression

At this closeout, local `main` and live remote `main` both identify
`45f5791f98d3cb5cffbdaa960066aefa2be6bae9`. The SPEC-009 merge commit is therefore
the current main head; `git merge-base --is-ancestor` also succeeds.

The existing main push workflow was explicitly rerun for this task:
[CI run 34042433176, attempt 2](https://github.com/steemchen-creator/AIC/actions/runs/34042433176/attempts/2).
It started at `2026-09-06T15:51:01Z`, completed at `2026-09-06T15:52:39Z`, and
reports `head_sha = 45f5791f98d3cb5cffbdaa960066aefa2be6bae9` with success.
This is a new regression on merged main, not reuse of the feature-head run.

| Main regression gate | Result |
|---|---|
| `alembic upgrade head` and `pytest --cov --cov-report=term-missing` | 630 passed in 42.51s; no skipped or xfailed tests; branch coverage 97.40%, threshold 90% |
| Architecture tests | 29 passed as part of the full 630-test suite |
| PostgreSQL integration | Passed using the workflow's isolated PostgreSQL 17 service |
| ETF migration round-trip | Passed: 0013 -> 0012 -> 0013 -> 0012 -> head -> base -> head |
| `ruff check apps/backend/src apps/backend/tests` | All checks passed |
| `mypy` with repository strict configuration | No issues found in 124 source files |
| `dotnet build apps/desktop/AIC.Desktop.csproj --configuration Release` | Passed; 0 warnings, 0 errors |
| `git diff --check` | Passed locally |

The Python runner used CPython 3.12.14. These execution results come from GitHub
Actions, not a local Python/PostgreSQL/.NET installation. The ETF integration
file's three tests passed, including
`test_etf_index_migration_is_reversible_and_full_chain_rebuilds`. That existing
test executes each listed migration command with `check=True`. All downgrade
operations were confined to the disposable CI database; production data and
schemas were not touched.

## Impact assessment

The deviation damaged process integrity: the implementation reached `main`
before the required approval evidence was complete. Equal trees and passing
feature/main checks show no detected content damage or regression within the
tested scope; they do not prove that every possible defect is absent or
retroactively establish approval.

This task makes no changes to ETF / Index Domain, QDII / Nasdaq semantics, PIT,
execution profiles, T0/T1, fees/taxes, normalizers, portfolio accounting, Shadow
integration, migration 0013, or the direct-US boundary. Existing non-blocking
debt `S009-D01` through `S009-D05` remains deferred: relationship history, IOPV,
authoritative product rules/classification, optional authorized live smoke
tests, and provider revision history beyond insert-or-verify.

## Remediation and publication

The remediation consists of the tree attestation, exact feature-head CI check,
fresh latest-main regression, this substantive governance exception record,
and the feature-branch closeout. This record adds incident classification,
impact analysis, review authority, remediation, and prevention; it is not a
commit whose only purpose is to record its own SHA or a CI run identifier.

The governance documentation is submitted on the separate
`feature/spec009-governance-closeout` branch through a Draft PR targeting
`main`. It does not replace or reopen implementation PR #10. Its own commit
SHA, PR number, and checks are reported externally in the delivery response;
they are not written back into this record in a self-reference loop. The
documentation PR remains for Architecture Review and human disposition.

## Prevention

1. Keep subsequent implementation PRs Draft until Architecture Final Approval.
2. Treat Merge as a human release/governance decision, not an automatic
   development step. AI contributors must not self-merge.
3. Before a human merge, require a visible Architecture Final Approval and a
   Final HEAD attestation whose local, remote, PR and CI identities match.
4. Freeze the approved implementation head after attestation. A changed head
   requires fresh checks and review of the changed content.
5. Retain this exception and its deviation classification in later reviews;
   do not represent SPEC-009 as having followed the original process fully.

These are recorded workflow requirements. This task does not claim to have
enabled GitHub branch protection, required checks, or approval enforcement.

## Formal closeout and stop condition

The owner-authorized closeout classification, once the final branch cleanup
and clean-main checks in the external delivery attestation pass, is:

```text
SPEC-009 FINAL APPROVED WITH NON-BLOCKING DEBT
GOVERNANCE EXCEPTION RECORDED
PROCESS DEVIATION OCCURRED
```

The external attestation must confirm removal of the local and remote
`feature/etf-index-exposure` branches, current branch `main`, clean workspace,
local main equal to live `origin/main`, and SPEC-010 not started. Deletion is
limited to those exact feature refs after rechecking their expected head and
the preserved merged tree; the governance documentation branch remains for
review. Branch names are not required to keep the immutable PR, commits and CI
evidence accessible.

This conditional status is the owner's requested post-merge disposition, not
a fabricated independent Architecture Review approval. After the final
attestation, work stops for Architecture Review. No SPEC-010 work is authorized
or started by this closeout.
