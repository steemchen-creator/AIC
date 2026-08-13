# Deployment Documentation

Before starting a Phase 5 backend, provide `AIC_DATABASE_URL` from the environment and
run `alembic upgrade head`. Credentials must never be embedded in files or logs.

The PostgreSQL async engine owns connection pooling and pre-ping; repositories acquire
short-lived transaction/connection scopes. Deployment shutdown must dispose the engine.
Migration failure blocks rollout. Redis remains operational infrastructure only and is
not a canonical source of truth.
