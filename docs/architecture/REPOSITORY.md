# Repository, Cache, and Event Contracts

## Repository

`DataRepository` owns durable-record semantics through `get(record_id)` and
`save(record)`. The contract does not expose SQLAlchemy sessions, tables, query
objects, or database-specific errors.

## Cache

`DataCache` owns temporary record lookup through `get(record_id)` and
`set(record)`. It does not decide when a record should be fetched or persisted.
Expiry and invalidation are deferred until a real caching requirement exists.

## Event bus

`EventBus` publishes `DataRecordReceived`. It does not own event creation or
application decisions.

## TASK-002 adapters

The three adapters use independent in-memory collections. They prove contract
replaceability and deterministic behavior without database schemas, Redis data,
brokers, credentials, or external services. They are process-local and are not
production durability mechanisms.
