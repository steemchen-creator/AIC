# Database Documentation

PostgreSQL is the canonical database. SPEC-004 Phase 5 introduces
`canonical_daily_bars`, owned by the Data Foundation persistence adapter.

The table uses `record_id` as its immutable primary key and stores DailyBar identity,
exact NUMERIC prices/turnover, timestamps, provenance, observation ID/raw hash and the
first ingestion-time quality snapshot. It has no `updated_at`: canonical facts and V1
quality snapshots are never overwritten.

Schema changes use Alembic under `migrations/`. Apply with `alembic upgrade head` using
`AIC_DATABASE_URL`. Roll back this initial migration with `alembic downgrade base` only
in an approved environment; it drops the table and its data. Production backup,
retention and recovery policies remain deployment responsibilities and require review.

SPEC-004 Phase 6 migration `20260814_0002` expands `record_id` from 64 to 80
characters so the existing `rec_` plus SHA-256 deterministic identity fits without
changing identity semantics. Upgrade is non-destructive. Downgrade restores 64 and
must only run when no stored record ID exceeds that limit.
