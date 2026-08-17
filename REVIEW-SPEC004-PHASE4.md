# SPEC-004 Phase 4 Architecture Review Evidence

## 1. Executive Summary

Phase 4 implements a deterministic, auditable Raw-to-Canonical path for the fixture
DailyBar only. It reuses Phase 1 identity/provenance, Phase 2 Validation and Phase 3
Quality without adding persistence, networking or a real Provider.

## 2. Git / PR Status

- Branch: `feature/real-data-foundation`
- Draft PR: [#5](https://github.com/steemchen-creator/AIC/pull/5)
- Base: `main`
- Implementation SHA: `e218cd14b0ba2baf2c6beca6301055b94b635e13`
- Implementation CI: `31683202366` — passed
- Final HEAD / remote HEAD / PR head: the commit containing this review; exact equal
  SHA and final CI Run ID are attested in the immutable PR #5 timeline after CI. A Git
  commit cannot embed its own content-derived SHA without changing that SHA.

## 3. Architecture Diff

Two cohesive flat modules were added: `normalization.py` owns the source mapping
boundary; `ingestion.py` owns orchestration and typed outcomes. No directory was added
for a single implementation and no existing layer was restructured.

## 4. Added / Modified Files

Added:

- `apps/backend/src/aic_backend/data_foundation/normalization.py`
- `apps/backend/src/aic_backend/data_foundation/ingestion.py`
- `apps/backend/tests/data_foundation/test_ingestion_pipeline.py`
- `REVIEW-SPEC004-PHASE4.md`

Modified:

- `apps/backend/src/aic_backend/data_foundation/__init__.py`
- `apps/backend/tests/architecture/test_dependencies.py`
- `docs/specifications/SPEC-004-Real-Data-Foundation.md`
- `docs/architecture/DATA_FOUNDATION.md`
- `docs/testing/DATA_FOUNDATION.md`
- `CHANGELOG.md`

## 5. Raw-to-Canonical Architecture

`RawObservation -> DataNormalizer -> DailyBar -> Validator -> DataQualityAssessor ->
IngestionSuccess | IngestionFailure`. The pipeline contains control flow only.

## 6. Normalizer Protocol

`DataNormalizer[T]` exposes a stable `transformation_version` and pure `normalize()`.
The protocol has no I/O, Runtime or adapter dependency.

## 7. Fixture DailyBar Normalizer

`FixtureDailyBarNormalizer` is explicitly fixture-only. It is selected through a copied
allowlist mapping and cannot dynamically load code or pretend to be a real Provider.

## 8. Raw Observation Flow

The normalizer accepts only the existing `RawObservation`; callers cannot pass a raw
Provider response directly to DailyBar construction through this pipeline.

## 9. Parsing Rules

Text, integer, Decimal, date, datetime, boolean and enum inputs are parsed explicitly.
Float-to-Decimal conversion is rejected. Missing/type/value/schema errors have stable
codes and fields.

## 10. Instrument Mapping

Fixture `market`, `ticker` and `instrument_type` map to the existing
`InstrumentIdentity`. Raw names remain confined to fixture payload normalization.

## 11. Timestamp Mapping

`event_time` and optional `provider_timestamp` must be timezone-aware. `received_at`
comes from RawObservation. `trading_date` is parsed independently as the market date.
There is no implicit system clock read.

## 12. Provenance Construction

The result reuses provider ID, source ID/URI/timestamp, failover fields and payload hash
from RawObservation metadata. `raw_payload_hash` is not recalculated by a second method.

## 13. Failover Metadata Propagation

`received_via_failover` and `failover_count` are copied exactly. Phase 3 alone adds
`SOURCE_FALLBACK`; the pipeline applies no extra deduction or interpretation.

## 14. Validation Integration

The injected existing `Validator` runs after normalization. Invalid results stop the
success path, retain observation/provider identity and the complete ValidationResult,
and never call Quality.

## 15. Quality Integration

The injected existing `DataQualityAssessor` runs only after Validation passes.
`reference_time` and `QualityContext` are explicit inputs. No weights or formula are
present in the pipeline.

## 16. Ingestion Success Model

Frozen `IngestionSuccess` records ingestion, observation and record IDs, the typed
DailyBar, provenance, validation and quality results.

## 17. Ingestion Failure Model

Frozen `IngestionFailure` records execution/source identity, failure category,
normalization code/field and optional ValidationResult.

## 18. Error Taxonomy

Normalization defines unsupported-record, missing-field, invalid-type, invalid-value
and unsupported-schema codes. Ingestion distinguishes raw-observation, normalization,
validation, quality-input and unsupported-record categories. Only expected structured
data errors are converted; programming errors propagate.

## 19. Transformation Version

The fixture version is the stable non-empty `fixture-daily-bar-v1` and is copied from
the actual normalizer into `DataProvenance.transformation_version`.

## 20. Determinism Evidence

`test_pipeline_is_deterministic_except_explicit_ingestion_identity_and_no_mutation`
runs the path 100 times and compares record and quality results.

## 21. Record Identity Stability

Tests prove mapping order and quality reference-time changes do not affect record ID.
Execution-level `ingestion_id` is never an input to `deterministic_record_id`.

## 22. No Mutation Evidence

Tests compare the source dictionary and QualityContext after execution and verify the
RawObservation payload remains an immutable `MappingProxyType`.

## 23. No Auto-Correction Evidence

Invalid OHLC and negative volume reach the existing validator and fail. The normalizer
does not change high, low, volume or timestamps to make them pass.

## 24. Provider Runtime Boundary

No SPEC-003 file changed. Architecture tests prohibit imports of Provider Runtime and
its Selector, Lifecycle, Health, Registry and Failover internals.

## 25. Architecture Boundary Review

AST tests prohibit database, network, filesystem writes, Presentation, Infrastructure,
real Provider and future pipeline responsibilities. They also detect raw-field leakage
and copied Validation/Quality rules.

## 26. E2E Fixture Evidence

The 29 Phase 4 tests cover successful DailyBar mapping, stable failures, key-order hash,
100-run determinism, validation short-circuit, failover, conflicts, timestamps,
identity, mutation and unexpected-programming-error propagation.

## 27. Test Evidence

- Full backend: `294 passed`
- Phase 4 focused: `29 passed`
- Architecture: `16 passed`
- Skip/xfail: none reported

## 28. Coverage

- Full repository: `94.08%` (required 90%)
- `normalization.py`: `100%`
- `ingestion.py`: `100%`
- Phase 1–3 core modules remained at `100%` in the full report

## 29. Ruff

`python -m ruff check .` passed.

## 30. Mypy

`python -m mypy` passed in strict mode for 64 source files.

## 31. Architecture Tests

`python -m pytest apps/backend/tests/architecture -q` passed: `16 passed`.

## 32. WPF Build

Release build passed with 0 warnings and 0 errors for
`apps/desktop/AIC.Desktop.csproj`.

## 33. GitHub Actions

Implementation CI Run `31683202366` passed Governance baseline, Backend tests and
Desktop build. The required CI run for the final review-containing HEAD is recorded in
the PR #5 final attestation after that run completes.

## 34. Known Limitations

Only the deterministic fixture DailyBar schema `1.0` is supported. The pipeline is
synchronous and in-memory; it deliberately has no durability or operational retries.

## 35. Technical Debt

No blocking debt was introduced. Future Providers need separately reviewed normalizers
and explicit registration. Persistence/idempotent writes remain a Phase 5 concern.

## 36. Scope Confirmation

- Phase 5 not started; Persistence not implemented.
- Database unchanged; no migration added.
- No real Provider or network I/O introduced.
- Retry and Reconciliation not implemented.
- No investment strategy implemented.
- SPEC-003 Provider Runtime not modified.
- PR #5 remains Draft and is not merged.

## 37. Final Recommendation

Recommend architecture review of Phase 4. The implementation meets the approved scope,
preserves layer boundaries and supplies deterministic automated evidence. Do not begin
Phase 5 or merge PR #5 until reviewer approval.
