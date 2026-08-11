# Provider Runtime testing

Phase 3 verification is deterministic: tests inject a fixed UTC clock, fixed ID
generator, explicit Provider responses, and short local timeouts. No external
service or random input is used.

Coverage includes:

- allowed and rejected lifecycle transitions;
- successful and failed initialization;
- shutdown and terminal state behavior;
- successful and timed-out health checks;
- consecutive-failure degradation and unavailability;
- threshold-based two-step recovery;
- cancellation of background health tasks;
- serialization of concurrent status changes;
- architecture enforcement of exclusive lifecycle state ownership.

Phase 4 additionally verifies immutable request and metrics inputs, every
filter category, preferred/excluded precedence, stable sorting, scoring boundary
values and defaults, immutable decisions, distinct no-candidate errors, and
1,000 deterministic selections across 100 Mock Provider snapshots. Selection
and scoring remain network-free pure calculations.

Phase 5 verifies successful standardization, known and unknown Provider errors,
invalid responses, unavailable state, unsupported Capability, timeout-driven
cancellation, external task cancellation, capacity release on every exit path,
and concurrent calls under a deterministic per-Provider limit.

Run the full quality gate from the repository root:

```powershell
.venv\Scripts\python.exe -m pytest --cov --cov-report=term-missing
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy apps/backend/src/aic_backend
dotnet build apps/desktop/AIC.Desktop.csproj --configuration Release
```
