# Data Foundation API

## `GET /data/{record_id}`

Retrieves a source-neutral record through the Application use case. The route does not access providers, repositories, caches, databases, or Redis directly.

TASK-002 exposes one deterministic mock record at `GET /data/sample-1`:

```json
{
  "record_id": "sample-1",
  "source": "mock",
  "payload": {"value": 42},
  "observed_at": "2026-01-01T00:00:00Z"
}
```

An unknown identifier returns HTTP `404` with `Data record not found`. Existing `GET /` and `GET /health` behavior remains unchanged.

No real data-source, stock, market, financial, news, AI, or strategy endpoint is part of TASK-002.
