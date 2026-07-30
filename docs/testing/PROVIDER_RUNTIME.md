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

Run the full quality gate from the repository root:

```powershell
.venv\Scripts\python.exe -m pytest --cov --cov-report=term-missing
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy apps/backend/src/aic_backend
dotnet build apps/desktop/AIC.Desktop.csproj --configuration Release
```
