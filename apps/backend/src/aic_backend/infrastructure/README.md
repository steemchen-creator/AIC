# Infrastructure

## Responsibility

Implement Application-owned repository, cache, event bus, and operational
service contracts.

## Boundary

Infrastructure may depend on Application and Domain contracts. TASK-002 data
adapters are process-local and deterministic; existing database and Redis
connectivity remain startup checks only.

## Prohibited

- Business or use-case decisions
- Provider or Presentation imports
- Vendor data access
- Database schema or production persistence changes without a reviewed task

## Future extension

Durable SQL, Redis, and message-bus adapters may replace the in-memory adapters
through the same ports after their schema, migration, failure, and operations
policies are approved.
