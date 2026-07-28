# Provider Contract

## Owned interface

`DataProvider` is an asynchronous Application-owned protocol with one operation:

```text
fetch(record_id) -> DataRecord | None
```

`None` means the configured source has no matching record. Source failures and
operational policies are intentionally absent because TASK-002 uses no external
service.

## TASK-002 adapter

`MockDataProvider` accepts predefined Domain records and performs deterministic
in-memory lookup. It makes no HTTP calls and has no cache, repository, event, or
calculation responsibility.

## Replacement rule

A later provider must implement the same Application-owned contract and map its
source response into a Domain object. Application and Presentation code must not
import the concrete provider.
