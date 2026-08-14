# Deployment Documentation

Before starting a Phase 5 backend, provide `AIC_DATABASE_URL` from the environment and
run `alembic upgrade head`. Credentials must never be embedded in files or logs.

The PostgreSQL async engine owns connection pooling and pre-ping; repositories acquire
short-lived transaction/connection scopes. Deployment shutdown must dispose the engine.
Migration failure blocks rollout. Redis remains operational infrastructure only and is
not a canonical source of truth.

Inject `AIC_TUSHARE_TOKEN` through the deployment secret store. Example environment
files contain only an empty placeholder. Missing credentials leave the Provider
unavailable without exposing a token or crashing composition. Never pass the token on
the command line or commit a populated environment file.
