# REVIEW — SPEC-004 Phase 9

## 1. Executive Summary
A-share Instrument Master and daily Trading Status foundation implemented for SSE/SZSE.
## 2. Git / PR Status
Implementation is on `feature/real-data-foundation`; PR #5 remains Draft. Final SHA equality
and GitHub Actions are recorded after the final push.
## 3. Architecture Diff
Source-neutral Domain facts, Application ports/use cases, Tushare adapters and PostgreSQL adapters added.
## 4. Files
Instrument domain, normalizers, services, persistence, migration, tests and documentation.
## 5. Provider API Verification
Official Tushare `stock_basic` and `suspend_d` documentation was verified before coding:
<https://tushare.pro/document/1?doc_id=25> and
<https://tushare.pro/document/2?doc_id=214>.
## 6. Provider Capabilities
`instrument.master.read` and `instrument.trading_status.read` are separate from DailyBar/Calendar.
## 7. Instrument Identity
Existing exchange-aware `InstrumentIdentity` is reused; no second stock-ID system.
## 8. Instrument Master Model
Identity, current display name, lifecycle, listing status, retrieval time and provenance.
## 9. Listing Lifecycle
Listing/delisting dates are inclusive; missing lifecycle evidence remains unknown.
## 10. Trading Status Model
Date-specific `TRADING`, `SUSPENDED`, or `UNKNOWN` security facts.
## 11. Suspension Semantics
`S` maps to suspended; `R` proves trading only on resumption date; empty does not mean trading.
## 12. RawObservation
Provider Runtime returns sanitized immutable mappings before normalization.
## 13. Normalization
Vendor fields remain inside dedicated Tushare master/status normalizers.
## 14. Validation
Exchange, identity, name, lifecycle, status, dates, timezone and provenance are validated.
## 15. Provenance
Provider, source identity/URI, raw hash and transformation version are retained.
## 16. Repository Ports
Application owns exact/find/list master and exact/range status contracts.
## 17. PostgreSQL Schema
Migration 0005 adds master, status and append-only operational coverage tables.
## 18. Master Sync
Explicit SSE/SZSE and listing-status sync; ordinary reads never trigger all-market sync.
## 19. Trading Status Backfill
Instrument/range input, bounded sequential requests, partial stop and safe resume.
## 20. Coverage
Only completed Provider intervals establish coverage; absent facts remain absent.
## 21. Idempotency
Repeated canonical facts return `ALREADY_EXISTS`.
## 22. Identity Conflict
Different facts under one canonical identity fail without overwrite.
## 23. Historical Gap Classification
Market closed, not listed, delisted, suspended, probable gap, or unknown.
## 24. Calendar Integration
Calendar remains exchange-level; Instrument Trading Status remains security-level.
## 25. DailyBar Compatibility
DailyBar identity and event-time semantics are unchanged.
## 26. Error Mapping
Runtime and persistence retain structured sanitized error categories.
## 27. Observability
Only safe provider/capability/range/count/status context is permitted; no token/raw payload.
## 28. Migration Evidence
Previous-head downgrade and new-head upgrade are covered by PostgreSQL tests.
## 29. PostgreSQL Evidence
Round-trip, deterministic order, idempotency, conflict and coverage ledger are tested.
## 30. E2E Evidence
Runtime selection/invocation/failover → fixture → normalizers → PostgreSQL is deterministic.
## 31. Architecture Tests
Application/Tushare/HTTP/SQL and forbidden business-module boundaries are automated.
## 32. Test Evidence
`python -m pytest --cov -q`: 423 passed in 33.46s.
## 33. Coverage
Total 96.69%; instrument Domain 100%, normalizers 96%, application service 99%,
instrument persistence 97%, Historical gap classification 98%.
## 34. Ruff
`python -m ruff check .`: passed.
## 35. Mypy
`python -m mypy --strict apps/backend/src`: passed, 86 source files.
## 36. WPF
`dotnet build apps/desktop/AIC.Desktop.csproj -c Release --nologo`: passed,
0 warnings and 0 errors.
## 37. GitHub Actions
Exact final-HEAD run is externally attested to avoid an evidence-only commit loop.
## 38. Final HEAD Attestation
Local = remote = PR Head and clean workspace are verified after CI.
## 39. Known Limitations
No full name history, minute suspension, corporate actions, ST taxonomy, industries or second Provider.
## 40. Technical Debt
Temporal master revisions and continuing-suspension reconstruction require separate review.
## 41. Scope Confirmation
A-share Instrument Master, SSE/SZSE lifecycle, daily status/suspension foundation and Historical classification implemented. No real-time/minute/Tick/Level-2, corporate actions, strategy, AI decision, portfolio, paper/live trading, institutional intelligence, second Provider reconciliation, or UI. PR #5 remains Draft.
## 42. Final Recommendation
Review Draft PR #5 after exact final-HEAD CI attestation; do not merge or begin Phase 10.
