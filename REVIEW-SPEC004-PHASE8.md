# REVIEW — SPEC-004 Phase 8

## 1. Executive Summary
A-share Trading Calendar foundation implemented for SSE/SZSE on Draft PR #5.
## 2. Git / PR Status
Final SHA equality and CI are externally attested after the final push; PR #5 stays Draft.
## 3. Architecture Diff
Application-owned calendar ports/use cases, source-neutral canonical fact/policy, Tushare adapter and PostgreSQL adapters were added.
## 4. Added / Modified Files
Calendar domain, normalization, ports, service/backfill, persistence/migration, tests and affected documentation.
## 5. Calendar Canonical Model
`TradingSessionDay` stores market/date, explicit OPEN/CLOSED, optional session and provenance.
## 6. Exchange Model
Existing `CN.SSE` and `CN.SZSE` market identity is reused; no duplicate exchange enum.
## 7. Timezone Semantics
Asia/Shanghai policy inputs become timezone-aware UTC timestamps.
## 8. Session Semantics
V1 regular sessions are 09:30–11:30 and 13:00–15:00; the lunch break is explicit.
## 9. Provider Capability
`market.calendar.read` is separate from `market.daily.read` and independently selectable.
## 10. Tushare Calendar Adapter
Uses `trade_cal`; vendor date/exchange/open fields remain at the adapter boundary.
## 11. RawObservation / Normalization
Sanitized immutable rows are hashed and converted by the injected calendar normalizer.
## 12. Validation
Exchange/date/open flag, aware retrieval time, open/session consistency and session ordering are enforced.
## 13. Provenance
Provider, source identity/URI, retrieval time, raw hash and transformation version are retained.
## 14. Calendar Repository
Exact day, inclusive ordered range, OPEN filter and previous/next queries are supported.
## 15. PostgreSQL Schema
`trading_calendar_days` has market/date primary identity and an indexed range; the ledger is append-only.
## 16. Calendar Coverage
Only COMPLETED Provider request intervals establish coverage, including valid empty results.
## 17. Calendar Backfill
Explicit sequential bounded chunks use Runtime and stop on partial/failure for safe resume.
## 18. Idempotency
Repeated confirmed ranges cause no Provider call; identical facts return ALREADY_EXISTS.
## 19. Identity Conflict
Different canonical OPEN/session content under market/date is rejected, never overwritten.
## 20. Error Mapping
Provider, normalization, validation, persistence and identity errors remain structured and sanitized.
## 21. Historical Gap Integration
Under complete calendar coverage, OPEN dates without bars become candidate gaps; CLOSED dates do not.
## 22. Suspension Limitation
Candidate gap does not distinguish instrument suspension from missing market data.
## 23. DailyBar event_time Integration
Existing record identity/event time remains unchanged; future bars may consume Calendar close without rewrite.
## 24. Migration Evidence
Migration 0004 previous-head downgrade and head upgrade passed in the PostgreSQL suite.
## 25. PostgreSQL Evidence
PostgreSQL tests cover OPEN/CLOSED round-trip, order, idempotency, conflict, ledger and safe errors.
## 26. E2E Evidence
Runtime selector/invocation/failover → Tushare fixture → normalization → PostgreSQL → Historical gap is tested.
## 27. Architecture Tests
Application/Tushare/HTTP/SQL boundaries, no weekday heuristic and capability separation are automated.
## 28. Test Evidence
390 tests passed, including 21 architecture tests and PostgreSQL integration/E2E tests.
## 29. Coverage
Total 96.44%; calendar domain 100%; calendar normalizer 100%; calendar service/backfill 96%; calendar persistence 96%; historical gap integration 100%.
## 30. Ruff
Passed.
## 31. Mypy
Strict mode passed for 81 source files.
## 32. WPF Build
Release build passed with 0 warnings and 0 errors.
## 33. GitHub Actions
Exact final-HEAD run is externally attested to avoid an evidence-only commit loop.
## 34. Final HEAD Attestation
Local = remote = PR Head and clean workspace are verified after CI.
## 35. Known Limitations
No instrument suspension feed, special-session catalogue, auction engine or corporate-action adjustment.
## 36. Technical Debt
Authoritative special sessions, revisions and instrument trading status require separately reviewed phases.
## 37. Scope Confirmation
A-share Trading Calendar foundation implemented. SSE/SZSE calendar supported. Open/closed market dates supported. Canonical session semantics supported. Calendar persistence/backfill supported. Historical DailyBar gap detection integrated.

No real-time market data. No minute/Tick/Level-2. No complete auction/matching engine. No corporate actions/adjustment. No instrument suspension feed. No financial statements. No news/announcements. No institutional/social-security/national-team module. No second market-data Provider. No strategy. No AI investment decision. No portfolio. No paper trading. No live trading. No UI. PR #5 remains Draft.
## 38. Final Recommendation
Review Draft PR #5 after exact final-HEAD CI attestation; do not merge or begin Phase 9.
