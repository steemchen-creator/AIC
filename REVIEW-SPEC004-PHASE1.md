# SPEC-004 Phase 1 Review

Review date: 2026-08-13

Branch: `feature/real-data-foundation`

## 1. Executive Summary

SPEC-004 Phase 1 establishes the immutable, source-neutral model foundation required
before real financial data can enter AIC. It adds typed instrument, provenance, Raw
Observation, Canonical Record and `DailyBar` values plus deterministic record identity
and canonical raw hashing. It preserves the existing TASK-002 API and does not modify
SPEC-003 Provider Runtime.

Local acceptance is complete: 197 tests pass, repository coverage is 93.77%, Phase 1
core coverage is 98.65%, and all static, architecture and desktop gates pass.

## 2. Git / PR Status

- Base: latest `main` at `fdee784b1436b32bd60e8d7ec357f29b87361f82`.
- Branch: `feature/real-data-foundation`.
- Draft PR: created after this review file is committed and pushed.
- Merge: not authorized; review required.
- Workspace: expected clean after publication.

## 3. Architecture Diff

```text
domain/
  market_data/        pure enums, errors and immutable financial-data values
data_foundation/      deterministic identity, hashing and construction helpers
```

`domain.market_data` is standard-library-only. `data_foundation` depends inward on
that domain package. Neither package imports Provider Runtime, Infrastructure,
Presentation, FastAPI, WPF, a network client, database package or vendor SDK.

## 4. Added / Modified Files

Added:

- `apps/backend/src/aic_backend/domain/market_data/{__init__,enums,errors,models}.py`
- `apps/backend/src/aic_backend/data_foundation/{__init__,canonical,identity}.py`
- `apps/backend/tests/data_foundation/test_identity.py`
- `apps/backend/tests/data_foundation/test_market_data_models.py`
- `docs/specifications/SPEC-004-Real-Data-Foundation.md`
- `REVIEW-SPEC004-PHASE1.md`

Modified:

- domain exports and architecture dependency tests;
- `pyproject.toml` coverage sources;
- `README.md`, `CHANGELOG.md`, Data Foundation architecture/testing documents.

## 5. Domain Models

`CanonicalRecord` is the general envelope. `DailyBar` is the first typed canonical
foundation and contains instrument, market trading date, three timestamps, provenance,
OHLC, volume and turnover. The envelope does not replace typed records.

Phase 1 enforces structural domain invariants only. It deliberately accepts values
such as inconsistent OHLC or negative volume so Phase 2 owns financial validation in
one explicit engine rather than hiding it in constructors.

## 6. Instrument Identity

`InstrumentIdentity` combines `Market`, normalized symbol and `InstrumentType`.
Canonical keys are market-qualified, for example `CN.SSE.600519`. Market and type are
both record-identity inputs, preventing cross-market and cross-instrument ambiguity.
This is a foundation, not a complete Security Master.

## 7. Timestamp Semantics

`event_time`, `observed_at`, `ingested_at`, `received_at` and optional provider time
must be timezone-aware and are normalized deterministically to UTC. `trading_date`
remains a separate `date` representing the source market calendar day. Tests prove a
China-market trading date is not replaced by the preceding UTC date.

## 8. Deterministic Identity

`deterministic_record_id` canonicalizes record type and UTC event time, then hashes a
versioned representation of instrument key, instrument type, record type, time and
domain discriminator with SHA-256. It uses no current time, UUID, Python `hash()`,
randomness or process state. Equivalent time instants generate the same ID.

## 9. Raw Payload Hash

`raw_payload_hash` uses SHA-256 and type delimiters for bytes, text and mappings.
Mappings are recursively serialized with sorted string keys and explicit tags for
`Decimal`, `date` and `datetime`. Key insertion order does not change the digest, and
bytes cannot collide with equal-looking text through shared serialization.

## 10. Provenance Model

`DataProvenance` records provider ID, optional source record/URI/timestamp, failover
attribution, raw SHA-256 hash and transformation version. It rejects malformed hashes,
negative or inconsistent failover attribution, naive provider timestamps and source
URIs containing user info or common credential query keys.

## 11. Immutability Strategy

All models are frozen and slotted. Mapping inputs are defensively copied recursively,
wrapped in immutable mapping views, and nested lists/tuples become tuples. Arbitrary
opaque objects and invalid keys are rejected, preventing payload from becoming an
untyped escape hatch. Mutation of original inputs cannot alter constructed records.

## 12. Decimal Strategy

`DailyBar` prices and turnover require `Decimal`; binary float is rejected. Volume is
an integer and boolean is rejected despite Python's `bool`/`int` relationship. Raw and
canonical payload serialization preserves `Decimal` as a tagged exact string.

## 13. Architecture Boundary Review

Automated import/source tests confirm:

- Domain does not depend on Provider Runtime or Application;
- Data Foundation does not depend on FastAPI, Infrastructure or Provider Runtime;
- no WPF or concrete Provider SDK import exists;
- Phase 1 contains no HTTP client, network call or database access;
- no Validation Engine, Quality Engine or persistence implementation exists;
- existing SPEC-003 boundaries remain enforced.

## 14. Test Evidence

Full command:

```text
.venv\Scripts\python.exe -m pytest -q --cov --cov-report=term-missing -ra
```

Result: **197 passed in 4.47s**. No skip, xfail or warning was reported.

Phase 1 tests cover same-fact identity, every required identity discriminator, mapping
order, timestamp awareness/conversion, trading-date rollover, provenance fields and
secret rejection, defensive copying, nested immutability, Decimal behavior, and
typed-model comparisons.

## 15. Coverage

- Full configured repository coverage: **93.77%**.
- Phase 1 Data Foundation + market-data Domain: **98.65%**.
- `data_foundation.identity`: 100%.
- `data_foundation.canonical`: 100%.
- `domain.market_data.models`: 98%.
- Required Phase 1 threshold: at least 95%; passed.

## 16. Ruff

Command: `.venv\Scripts\python.exe -m ruff check apps/backend/src apps/backend/tests tests`

Result: **Passed — All checks passed.**

## 17. Mypy

Command: `.venv\Scripts\python.exe -m mypy --strict apps/backend/src`

Result: **Passed — no issues in 51 source files.**

## 18. Architecture Tests

Command: `.venv\Scripts\python.exe -m pytest apps/backend/tests/architecture -q`

Result: **12 passed in 0.11s.**

## 19. WPF Build

Command: `dotnet build apps/desktop/AIC.Desktop.csproj --configuration Release --no-restore`

Result: **Passed — 0 warnings, 0 errors.**

## 20. GitHub Actions

Status at document creation: **Pending publication**. The Draft PR CI must complete
before Phase 1 handoff. Final run status and URL will be recorded in the PR and final
delivery response; a CI failure blocks handoff.

## 21. Known Limitations

- Only SSE and SZSE market codes and Equity, ETF and Index types are defined.
- `DailyBar` is the only typed canonical model.
- Canonical payload supports an explicit safe value vocabulary, not arbitrary objects.
- No Validation Result or financial semantic validation exists.
- No Data Quality Assessment or freshness policy exists.
- No normalization/ingestion pipeline exists.
- No raw/canonical repository, migration or persistence exists.
- No real Provider or network integration exists.

## 22. Technical Debt

| ID | Item | Severity | Disposition |
|---|---|---:|---|
| TD-004-01 | Market and instrument enums are intentionally minimal | Low | Expand only with approved real-data scope |
| TD-004-02 | Canonical envelope has no quality field in Phase 1 | Low | Add with Phase 3 owned assessment model |
| TD-004-03 | Source URI secret-key denylist is defense-in-depth, not a full credential detector | Medium | Enforce adapter logging/error contract before real Provider |
| TD-004-04 | Identity version is internal constant `1` | Low | Formalize migration policy before persistent IDs |

None blocks Phase 1 because no external provider, persistence or consumer is connected.

## 23. Scope Confirmation

Confirmed:

- Phase 2 has not started.
- Validation Engine is not implemented.
- Quality Engine is not implemented.
- Persistence is not implemented.
- No real Provider is connected.
- Provider Runtime state, selection, scoring and failover are unchanged.
- No API, database, migration, network, UI, strategy or AI behavior was added.

## 24. Final Recommendation

**APPROVED FOR PHASE 1 ARCHITECTURE REVIEW**, conditional only on the Draft PR GitHub
Actions passing. The implementation satisfies the Phase 1 model, provenance,
determinism, time, immutability, Decimal, architecture and documentation requirements.
Stop after Draft PR publication and wait for Architecture Review before Phase 2.
