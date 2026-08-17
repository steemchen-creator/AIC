# SPEC-004 Phase 3 Review

Review date: 2026-08-13

Branch: `feature/real-data-foundation`

## 1. Executive Summary

Phase 3 adds a pure, deterministic Data Quality Engine for validated DailyBar records.
It produces explainable component scores and stable flags, represents exact cross-source
conflicts without reconciliation, and leaves record identity and Provider Runtime intact.
Local acceptance passes with 263 tests and 100% Quality Engine coverage.

## 2. Git / PR Status

- Existing Draft PR: [#5](https://github.com/steemchen-creator/AIC/pull/5).
- Branch: `feature/real-data-foundation`; base: `main`.
- PR remains Draft; merge is not authorized.
- Final reviewed Phase 3 HEAD: `15c354ae0ec98a5dead318ca3523eedbfec912b1`.
- Remote branch HEAD: `15c354ae0ec98a5dead318ca3523eedbfec912b1`.
- PR #5 Head Commit: `15c354ae0ec98a5dead318ca3523eedbfec912b1`.
- Branch synchronization: local, remote and PR Head are identical.
- Workspace at evidence capture: **Clean**.

## 3. Architecture Diff

```text
data_foundation/quality/
|-- models.py       assessments, flags, context, policies and conflicts
|-- policies.py     four centralized pure component policies
|-- conflicts.py    exact Decimal conflict detection
|-- assessor.py     DailyBar composition and fixed weighting
`-- __init__.py     public Quality surface
```

## 4. Added / Modified Files

Added the five Quality package files and four focused test files for models, policies,
conflicts and DailyBar assessment. Modified Data Foundation exports, architecture tests,
SPEC-004 architecture/testing/specification documents and `CHANGELOG.md`. No Runtime,
API, database or migration file changed.

## 5. Data Quality Architecture

The caller supplies a DailyBar, explicit reference time, immutable `QualityContext` and
a successful Phase 2 `ValidationResult`. The assessor composes four independent pure
component functions and returns an immutable association; it performs no I/O or mutation.

## 6. DataQualityAssessment

The frozen/slotted model contains total, freshness, completeness, consistency and source
confidence scores plus flags. Scores clamp to 0–100 and round to two decimals. Flags are
deduplicated and deterministically sorted. It carries no payload, secret or free-text
business decision.

## 7. DataQualityFlag

The stable enum contains exactly the required V1 vocabulary: `STALE`, `INCOMPLETE`,
`SOURCE_FALLBACK`, `CONFLICTING_SOURCE`, `SUSPICIOUS_VALUE`,
`MISSING_OPTIONAL_FIELD`, and `UNKNOWN_SOURCE_TIMESTAMP`. SUSPICIOUS_VALUE has no
automatic rule because Phase 3 has no defensible anomaly policy.

## 8. Quality Formula

```text
score = freshness * 0.30
      + completeness * 0.25
      + consistency * 0.25
      + source confidence * 0.20
```

Weights are module constants. The final model clamps and rounds once to two decimals.
No ML, market outcome, stock movement or Provider Runtime score is an input.

## 9. Freshness Policy

DailyBar defaults are centralized: age through 1 day scores 100; between 1 and 7 days
declines linearly; 7 days or later scores 0 and adds STALE. Reference time is explicit.
Naive times and future event time are rejected. No weekend, holiday, suspension or
trading-calendar inference exists.

## 10. Completeness Policy

The policy names optional fields and an incomplete threshold. Source-declared
unavailable fields are removed from the denominator. All present scores 100; a partial
gap above threshold adds MISSING_OPTIONAL_FIELD; a score at/below threshold adds
INCOMPLETE. Required fields remain Validation's responsibility. Typed DailyBar turnover
is currently required, so normal assessment is complete.

## 11. Consistency Policy

No conflict scores 100. Otherwise the score is `100 * (1 - affected comparable fields /
all comparable fields)` and adds CONFLICTING_SOURCE. Each field is counted once. This
does not repeat OHLC legality checks from Validation.

## 12. Source Confidence Policy

Centralized V1 mapping: OFFICIAL_EXCHANGE 100, LICENSED_VENDOR 90,
PUBLIC_FINANCIAL_API 70, DERIVED_SOURCE 50, UNKNOWN 30. An unrecognized object safely
uses UNKNOWN. These values are configurable AIC policy, not objective vendor claims.

## 13. Failover Flag Behavior

`received_via_failover=True` adds SOURCE_FALLBACK. It does not reduce source confidence
or apply a second deduction. False produces no fallback flag.

## 14. Conflict Representation

`DataConflict` identifies logical record and field and holds sorted immutable
`ConflictValue` items containing Provider ID, exact Decimal value and optional aware
observation time. There is no winner or average property.

## 15. Conflict Detection

`ConflictDetector` returns no conflict when all Decimal values are exactly equal and a
structured conflict when at least two distinct values exist. It never converts to float,
selects a Provider, overwrites a record or applies tolerance.

## 16. Record Identity Stability

Quality is separate from Canonical/typed records and is absent from
`deterministic_record_id`. Tests assess the same record at different reference times,
obtain different freshness, and prove `record_id` is unchanged.

## 17. Determinism Evidence

The same record/reference/context/ValidationResult is assessed 100 times with complete
assessment equality. Flags, component scores and total are identical. A 10,000-item
pure batch smoke test also returns the same result without a flaky time threshold.

## 18. No Mutation Evidence

Tests compare frozen DailyBar, Provenance and QualityContext before/after assessment.
Conflict tuples and values remain unchanged. No record field is repaired, enriched,
selected, averaged or overwritten.

## 19. Validation / Quality Boundary

An invalid `ValidationResult` raises `InvalidQualityInputError`. Quality does not rerun
or copy required-field, timestamp, OHLC or non-negative rules. Unknown Provider timestamp
is legal and becomes an annotation, not a Validation error.

## 20. Provider Runtime / Data Quality Boundary

SPEC-003 QualityScorer ranks Providers; this Engine describes one record's quality.
Architecture tests prohibit Runtime imports, `QualityScorer` and `ProviderSelector`.
Data quality cannot alter Provider status, ranking, selection or failover.

## 21. Architecture Boundary Review

AST/source tests reject Provider Runtime, concrete Providers, Infrastructure,
Presentation, FastAPI, HTTP clients, database packages, file/network operations,
Persistence, Phase 4 pipelines and real SDKs. Quality depends inward only on Domain and
the Validation result contract.

## 22. Test Evidence

Command: `.venv\Scripts\python.exe -m pytest -q --cov --cov-report=term-missing -ra`

Result: **263 passed in 5.96s**; no skip, xfail or warning. Required freshness,
completeness, classifications, fallback, conflict, Decimal, identity, determinism,
mutation and batch scenarios are covered.

## 23. Coverage

- Full configured coverage: **95.43%**.
- Data Quality Engine: **100% statement/branch**.
- DailyBarQualityAssessor module: **100%**.
- Required core threshold: at least 95%; passed.

## 24. Ruff

`ruff check apps/backend/src apps/backend/tests tests`: **Passed**.

## 25. Mypy

`mypy --strict apps/backend/src`: **Passed; no issues in 62 source files**.

## 26. Architecture Tests

`pytest apps/backend/tests/architecture -q`: **14 passed in 0.13s**.

## 27. WPF Build

Release build: **Passed; 0 warnings and 0 errors**.

## 28. GitHub Actions

Draft PR #5 CI run
[`31678875530`](https://github.com/steemchen-creator/AIC/actions/runs/31678875530):

- Governance baseline: **Passed** in 3s.
- Backend tests: **Passed** in 44s.
- Desktop build: **Passed** in 57s.

This run verified final reviewed Phase 3 HEAD
`15c354ae0ec98a5dead318ca3523eedbfec912b1`, including the implementation and its
evidence-only document commit. At capture time, local HEAD, remote branch HEAD and PR #5
Head were identical and the workspace was clean.

**Final HEAD CI: PASSED. PR #5: Draft. Workspace: Clean. Phase 4: NOT STARTED.**

This evidence correction changes documentation only. To avoid an impossible
self-referential commit loop, the correction commit's exact SHA and its own required
check run are attested in the PR timeline and final delivery response after that run
completes; no implementation file is changed by the correction.

## 29. Known Limitations

- DailyBar is the only assessed typed record.
- Freshness does not know trading calendars, weekends, holidays or suspensions.
- Source confidence values are policy defaults without real-source evidence.
- Conflict comparison is exact; no configured tolerance exists.
- No suspicious-value detector is implemented.
- No consumer-specific usable/unusable threshold exists.
- Typed DailyBar currently has no missing optional field in valid instances.

## 30. Technical Debt

| ID | Description | Severity | Disposition |
|---|---|---:|---|
| TD-004-09 | V1 source confidence values require evidence before real Provider | Medium | Phase 6 Provider-specific review |
| TD-004-10 | No market calendar for DailyBar freshness | Medium | Dedicated calendar capability |
| TD-004-11 | Exact-only conflict comparison | Low | Add tolerance only with approved domain evidence |
| TD-004-12 | Quality association is not persisted | Low | Phase 5 persistence review |

No debt blocks the pure Phase 3 foundation.

## 31. Scope Confirmation

- Phase 4 has not started.
- Normalization and complete Ingestion Pipeline are not implemented.
- Persistence, database and migrations are unchanged.
- No real Provider is connected.
- Reconciliation, investment strategy, rating and AI judgment are absent.
- SPEC-003 Provider Runtime and its Quality Score are unchanged.

## 32. Final Recommendation

**APPROVED FOR PHASE 3 ARCHITECTURE REVIEW.** Final reviewed HEAD CI passed.
The Engine satisfies explainability, determinism, purity, identity stability, conflict
representation, coverage and architecture boundaries. Stop and wait; do not begin
Phase 4.
