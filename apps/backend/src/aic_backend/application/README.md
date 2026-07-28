# Application

## Responsibility

Own use cases and the outbound contracts they require.

## Boundary

Application may depend on Domain. Concrete providers, storage, caches, event
buses, HTTP frameworks, and dependency-injection wiring depend on Application,
not the reverse.

## Prohibited

- Vendor SDK or concrete infrastructure imports
- FastAPI route and response code
- SQL, Redis commands, or framework-specific persistence models

## Future extension

Add a use case only when an approved task introduces observable application
behavior. Add the narrowest port required by that use case.
