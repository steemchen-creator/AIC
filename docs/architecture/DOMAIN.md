# Domain Contract

## Model

`DataRecord` is the only TASK-002 data aggregate. It contains:

- `record_id`: source-neutral identity supplied at the application boundary.
- `source`: owned provider identifier, not a vendor SDK type.
- `payload`: immutable generic content pending future typed-domain tasks.
- `observed_at`: timezone-aware observation timestamp.

The model rejects blank identity fields and timestamps without timezone
information. It defensively copies and freezes its payload.

## Event

`DataRecordReceived` states that a record supplied by a provider has crossed
into the owned data boundary. It contains `event_id`, record identity, source,
an immutable payload snapshot, and a timezone-aware event timestamp.

The event rejects blank `event_id` and `record_id` values, rejects timestamps
without timezone information, and defensively copies and freezes its payload.

## Dependencies

Both types use Python standard-library features only. They contain no framework,
storage, transport, cache, vendor, or stock-specific types.
