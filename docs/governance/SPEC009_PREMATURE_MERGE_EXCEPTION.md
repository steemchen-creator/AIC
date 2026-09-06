# SPEC-009 Premature Merge Governance Exception and Publication Status

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
| remediation_authorized_by | Project owner via explicit `FIX-SPEC009-002` execution authorization; `FIX-SPEC009-003` authorizes this documentation correction. |
| architecture_review_status | `APPROVED WITH NON-BLOCKING DEBT` |
| architecture_review_reference | External Chief Investment Architect review of `FIX-SPEC009-002`, performed after independent verification of PR #11, Feature HEAD CI, merged-main CI, and governance record content, as reported in sections 1-2 of the owner-provided `FIX-SPEC009-003-Governance-Semantics-Publication-and-Final-Closeout.md`. |
| architecture_review_scope | The external review verified the technical remediation and accepted the incident classification; `FIX-SPEC009-003` addresses its remaining authorization/approval and publication semantics blockers. |
| publication_reference | [Draft PR #11](https://github.com/steemchen-creator/AIC/pull/11), `feature/spec009-governance-closeout`, targeting `main`. |
| status | `REVIEWED_PENDING_PUBLICATION` |

Execution authorization permits the remediation work; it does not constitute
Architecture Approval. The architecture review status above comes from the
external review reported in `FIX-SPEC009-003`, independently of the owner's
execution authorization. The exception has been substantively reviewed and
approved, but formal repository closeout remains pending human merge of PR #11
and the post-publication verification below. While PR #11 is unmerged, this
record exists on the governance branch and has not been published to `main`.

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

At the `FIX-SPEC009-002` technical verification, local `main` and live remote
`main` both identified
`45f5791f98d3cb5cffbdaa960066aefa2be6bae9`. The SPEC-009 merge commit was therefore
the main head at that verification; `git merge-base --is-ancestor` also succeeded.

The existing main push workflow was explicitly rerun for `FIX-SPEC009-002`:
[CI run 34042433176, attempt 2](https://github.com/steemchen-creator/AIC/actions/runs/34042433176/attempts/2).
It started at `2026-09-06T15:51:01Z`, completed at `2026-09-06T15:52:39Z`, and
reports `head_sha = 45f5791f98d3cb5cffbdaa960066aefa2be6bae9` with success.
This was a new regression on merged main, not reuse of the feature-head run.

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

The governance documentation is submitted on
`feature/spec009-governance-closeout` through the existing Draft PR #11 targeting
`main`. It does not replace or reopen implementation PR #10. The correction's
own commit SHA and exact-head CI results are reported externally in the
delivery response and PR, avoiding a self-reference commit loop.

Publication to the governance branch establishes a reviewable document, but
formal repository recording requires human merge of PR #11 into `main` and
verification that the corrected record is present there. Deletion of the old
ETF implementation branch and a clean workspace do not satisfy that publication
gate. The current status remains `REVIEWED_PENDING_PUBLICATION` until the
post-merge closeout checks are complete.

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

### Non-blocking governance hardening debt

`main` currently has no Branch Protection / Required Approval enforcement.
The external review treats this as non-blocking governance debt for this
closeout. Future Governance Hardening should consider protecting `main`,
restricting direct pushes, requiring checks and PR reviews/approvals,
preventing merge while Draft, and including a human Architecture Approval
checklist in the merge process.

The prevention items above are documented workflow requirements. This task
does not change administrator-level repository settings or claim that these
automated enforcement controls have been enabled.

## Pre-publication stop condition

`FIX-SPEC009-003` corrects the governance documentation on the existing branch
and PR. Before handoff, commit and publish the correction, verify that local
HEAD, remote governance branch HEAD, and PR #11 Head match, and wait for the
Governance baseline, Backend tests, and Desktop build checks at that exact
HEAD to pass. Confirm that the PR contains documentation changes only and the
workspace is clean.

After those checks pass, the handoff state is:

```text
Record status: REVIEWED_PENDING_PUBLICATION
PR #11: DRAFT / OPEN / NOT MERGED
Architecture remediation: READY FOR HUMAN MERGE
Formal repository closeout: PENDING HUMAN MERGE AND POST-PUBLICATION VERIFICATION
SPEC-010: NOT STARTED
```

`READY FOR HUMAN MERGE` is the remediation handoff status; PR #11 remains
Draft. AI must stop for Architecture Review / human merge, must not merge PR
#11, and must not claim formal Closeout is complete at this pre-publication
stage. The governance branch must remain available until human publication.

## Post-publication formal closeout

Only after the user manually merges PR #11 may the subsequent final closeout:

1. Verify PR #11 is `MERGED` and identify its actual merge commit.
2. Switch to `main` and synchronize with `origin/main` without rewriting history.
3. Verify the corrected governance record is present in `main` and that `main`
   contains the PR #11 merge commit.
4. Confirm local main equals live `origin/main`.
5. Delete the local and remote `feature/spec009-governance-closeout` branches
   after verifying that they have no unmerged work.
6. Confirm a clean workspace on `main` and SPEC-010 still not started.

The previous `feature/etf-index-exposure` branch cleanup remains completed;
it does not substitute for publication and cleanup of the governance branch.
When all post-publication checks above pass, the final attestation may state:

```text
SPEC-009 FINAL APPROVED WITH NON-BLOCKING DEBT
GOVERNANCE EXCEPTION RECORDED
PROCESS DEVIATION OCCURRED
FORMAL CLOSEOUT COMPLETE
```

These are post-publication states, not the status of this unmerged PR. No
SPEC-010 work is authorized by this remediation or by the subsequent closeout.
