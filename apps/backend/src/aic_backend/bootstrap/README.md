# Bootstrap

## Responsibility

Select concrete adapters and inject them into Application use cases.

## Boundary

Bootstrap is the composition root and may import all backend layers solely to wire dependencies. No other package chooses concrete adapters.

## Prohibited

- Business rules, HTTP handlers, data transformations, or adapter behavior
- Environment secrets in source code

## Future extension

Replace a concrete adapter here when an approved task introduces a durable or external implementation.
