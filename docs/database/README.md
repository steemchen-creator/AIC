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

Migration `20260817_0004` adds `trading_calendar_days` keyed by market/date and the
append-only `calendar_backfill_attempts` coverage ledger. OPEN and CLOSED facts retain
first provenance and use insert-or-verify. Downgrade removes only Phase 8 calendar tables.

SPEC-004 Phase 7 migration `20260817_0003` adds
`daily_bar_backfill_attempts`, an operational append-only ledger for requested inclusive
ranges, Provider/capability attribution, UTC timing, outcome counts and sanitized error
codes. Only `COMPLETED` attempts establish coverage; `PARTIAL` and `FAILED` attempts are
retained for audit/resume. The composite range index supports instrument-scoped overlap
queries. Downgrade drops only this operational ledger, not canonical DailyBar facts.
# Phase 9 tables

Migration 0005 adds `instrument_masters`, `instrument_trading_statuses`, and append-only
`instrument_sync_attempts`. Canonical identity and instrument/date are unique;
insert-or-verify rejects conflicting facts without silent updates.

# SPEC-006 execution and risk evidence

Migration `20260903_0009` adds immutable `risk_decisions`, post-trade
`execution_risk_snapshots`, `settlement_rollovers`, `settlement_position_evidence` and
`execution_audit_events`. Stable IDs are primary keys. Replaying identical evidence is
insert-or-verify; a reused identity with different content raises an identity conflict and
is never silently overwritten. The migration is reversible to `20260820_0008`; production
downgrades require backup and explicit operational authorization.

# SPEC-007 Forward Paper Trading

Migration `20260904_0010` adds `paper_accounts`, `paper_sessions`,
`paper_order_intents`, `paper_performance_snapshots`, `paper_trade_episodes` and
`paper_account_state_events`. The account row stores the atomic recovery projection;
normalized tables preserve queryable audit evidence. Stable identities are insert-or-verify,
and finalized sessions are immutable. Downgrade to `20260903_0009` removes only these Paper
Trading tables and therefore requires backup and explicit authorization outside isolated tests.

# SPEC-008 Shadow Portfolio Experiments

Migration `20260906_0011` adds `shadow_experiment_groups`, `shadow_experiment_members`,
`shadow_group_sessions`, `shadow_comparison_snapshots` and `shadow_role_activities`.
The group row stores the atomic recovery projection; normalized rows preserve queryable,
insert-or-verify evidence. Manifest, Fairness Contract and Policy Bundle Hash are immutable;
sessions, comparisons and activity are append-only. Downgrade to `20260904_0010` removes only
SPEC-008 experiment evidence and requires backup plus explicit authorization outside isolated tests.

Migration `20260906_0012` adds append-only `shadow_role_profile_events`. Avatar changes are stored
as old/new reference audit facts while the original Manifest and normalized member row stay immutable.
The group recovery projection includes these events so the effective role profile and activity board can
be reconstructed after restart. Downgrade to `20260906_0011` removes only profile-update audit events.

# SPEC-010 Trade Plans

Migration `20260909_0014` adds `trade_plans` as the atomic recovery projection and normalized
`trade_plan_revisions`, `trade_plan_directives`, `trade_plan_execution_evidence` and
`trade_plan_outcomes`. Revisions and evidence use stable identities with insert-or-verify conflict
handling. A partial unique index on `(portfolio_id, instrument_key)` where status is `ACTIVE`
duplicates the application invariant at the database boundary. Pair-history and directive-time
indexes provide deterministic ordering. Downgrade to `20260906_0013` removes only SPEC-010 tables
and therefore requires backup and explicit authorization outside isolated validation.

Trade Plan saves lock the existing plan row before validating append-only history and hold that
lock through projection/evidence writes. Concurrent stale appends fail with `IDENTITY_CONFLICT`
and must reload before retrying. Regression tests observe actual PostgreSQL lock waits for
competing revision, directive and execution appends and verify both normalized and recovery
records. Automatic directives optionally carry a canonical `trigger_key` in existing JSON;
old payloads remain readable and appendable without a schema migration or history rewrite.

Migration `20260910_0015` adds the execution-owned `execution_order_claims` journal, keyed by the
deterministic order ID. An immutable claim contains the request and account's pre-state; its
single completed receipt contains the authoritative order/fill/rejection outcome and post-state.
Completion verifies claim ownership under a row lock and refuses changed receipts. Trade Plan
link writes remain a separate transaction and reconcile from this durable receipt after conflicts.
No existing table or evidence is rewritten. Repeated 0014/0015 and base/head round-trips are tested.
Downgrade removes this journal and therefore destroys deduplication history: stop execution and
back up the journal before an explicitly authorized production downgrade. Never delete an
unfinished claim or restart execution with an empty journal to retry an old directive.
