# Multi-Horizon Trade Plan Foundation

SPEC-010 adds an explicit planning layer between an investment decision and the existing
authoritative execution/risk foundation. It does not generate investment opinions. A caller must
provide the thesis, classification, deterministic quantity and policies before activation.

## Taxonomy and lifecycle

Investment horizons are `T`, `SHORT`, `MEDIUM_SHORT`, `MEDIUM`, `MEDIUM_LONG` and `LONG`.
Trading styles are `SWING`, `TREND`, `VALUE`, `EVENT`, `INDEX`, `MEAN_REVERSION` and `OTHER`.
Both are descriptive plan policy, not strategies. They are editable while a plan is `DRAFT` and
immutable after activation.
Instrument and portfolio identity are immutable from creation, including in `DRAFT`. Changing
either requires a new `plan_id`; draft thesis, taxonomy and policies remain editable.

```text
DRAFT -> ACTIVE -> COMPLETED | CANCELLED | EXPIRED | INVALIDATED
  |         |
  +------> CANCELLED
```

A terminal plan cannot reactivate. A successor has a new `plan_id`; therefore extending the
horizon of a losing active plan cannot hide the predecessor's result. Application validation and
a partial PostgreSQL unique index enforce one active plan per `(portfolio, instrument)`. The same
instrument can have independent Champion and Shadow plans because portfolio identity is part of
the key.

## Revisions and directives

Activation creates immutable revision 1. A permitted stop/target policy amendment creates the next
complete canonical revision with timestamp, reason, actor and source. Prior revisions are never
updated. Trailing high-water changes are also revisions, so a restart can reproduce the trigger.

Every decision produces an idempotently identified directive bound to an exact plan revision:

- `ENTRY` and `SCALE_IN` become BUY intents;
- `REDUCE` and `EXIT` become SELL intents;
- `HOLD` is evidence only and never becomes an order.

Execution checks the authoritative account and remaining instrument position: `ENTRY` requires
no position, `SCALE_IN` requires an existing position, `REDUCE` must sell strictly less than the
remaining quantity, and `EXIT` sells that entire remaining quantity. A caller-supplied quantity
hint cannot override account state, and another portfolio's account is rejected.

Executable directives call the existing `AShareExecutionService` contract through an
Application-owned protocol. The Trade Plan layer cannot declare a fill, bypass pre-trade risk or
alter cash, settlement, lot, limit, trading-status, concentration, turnover or fee rules. Its
execution link records plan/revision/directive, existing order/fill identities, and stable
rejection codes.

## Stops, targets and terminal evidence

The V1 evaluator supports deterministic hard stops, ordered profit targets, trailing stops,
time stops, structured thesis-invalidation events and expiry. Natural-language thesis text is
retained for audit but is never parsed as a signal. Invalid quantities, prices, state transitions,
versions or unsupported identities fail closed with `TRADE_PLAN_*` reason codes.

An automatic stop or target has a persisted canonical policy key. Repeated observations reuse
its pending directive; a fill or rejection consumes that trigger without automatically retrying
it. Ordered target evaluation proceeds to the next eligible unconsumed level. Equivalent decimal
spellings, unrelated revisions and trailing high-water updates do not rearm a policy; an explicit
change to its price/distance/deadline, action or quantity defines a different policy. Legacy
directives without keys are matched to their bound revision, conservatively consuming ambiguous
equal-action/quantity legacy targets instead of issuing duplicate orders.

Terminal outcome materialization links stored revisions, directives and execution evidence with
caller-supplied values derived from the authoritative portfolio/execution ledger. It reports
holding duration, realized P&L, remaining quantity, trigger flags, scale/reduce/rejection counts
and adherence. It is measurement evidence only and does not rank strategies.
Materialization fails with `TRADE_PLAN_OUTCOME_PENDING` until every executable directive has
fill or rejection evidence, including an EXIT issued by expiry or thesis invalidation. Rejection
is a resolved attempt but never counts as adherence. The resulting outcome remains immutable.

## PIT and next eligible open

`PlanObservation` keeps event and availability times distinct. Evaluation rejects any event or
availability later than `as_of`. `PointInTimeNextOpenCalendar` reads only the existing PIT trading
calendar and schedules a daily-bar directive no earlier than the next known eligible market open.
Execution rechecks that time and then lets the existing execution service re-evaluate current
calendar, tradability, price-limit, settlement and risk evidence. A future revision or bar is not
visible to an earlier evaluation.
Every directive creation path selects a revision whose effective and recorded times are both
visible at `as_of`, or fails closed. Thesis invalidation and expiry validate their terminal
transition before atomically saving the directive and terminal state. Failed validation or
calendar lookup leaves no partial directive or high-water revision. Historical trigger decisions
cannot consume future execution evidence or overwrite later trigger evidence.

## Asset and account boundaries

- A-share Equity and SSE/SZSE-listed ETF identities are accepted.
- Domestic ETFs and CN-listed Nasdaq-QDII ETFs use the same CNY identity boundary; the existing
  product execution profile remains responsible for T+0/T+1, lot and fee facts.
- `REFERENCE.INDEX` is rejected before activation and cannot become executable merely because a
  plan uses `INDEX` style.
- Direct US instruments, USD cash, FX, leverage and borrowing remain unsupported.
- Plans, revisions, directives, executions and outcomes remain scoped to their portfolio, keeping
  Champion and every Shadow member isolated.

## Persistence and recovery

`TradePlanRepository` has in-memory and PostgreSQL implementations with the same application
contract. The PostgreSQL adapter stores an atomic recovery projection plus normalized append-only
revision, directive, execution-link and outcome tables. Stable identities are insert-or-verify;
conflicting reuse is rejected. Migration `20260909_0014` upgrades from `20260906_0013` and its
downgrade removes only SPEC-010 tables. Production downgrade requires an approved backup and
change procedure because it deletes Trade Plan history.

Existing plan saves hold a PostgreSQL row lock while validating the latest aggregate and writing
the projection and normalized evidence in one transaction. A competing stale append is rejected
with `IDENTITY_CONFLICT`; its caller must reload and explicitly append to the current history.
It cannot silently replace another writer's revisions, directives or execution links. The optional
directive policy key uses existing JSON fields, needs no new migration, and preserves old payloads.

### Execution reconciliation after a Trade Plan conflict

Durable Trade Plan execution requires `IdempotentExecutionService` around the existing
`AShareExecutionService`, backed by `PostgreSQLExecutionJournal`. The application-owned
`AuthoritativeExecution.reconcile` contract runs before position checks: a previous full EXIT
must remain reconcilable even though the account is now flat. The deterministic order ID remains
derived solely from the directive ID. The returned outcome must match that directive's account,
instrument, side, quantity and eligible execution time.

Migration `20260910_0015` adds `execution_order_claims`. Its primary key makes exactly one caller
the owner of an order. Claim identity, request and pre-execution state are permanent; completion
stores one immutable authoritative outcome and post-execution recovery snapshot. Reusing an order
ID for a different request is rejected. The execution engine operates on a detached state through
the unchanged risk/accounting/settlement path. The live account projection is published only after
the completed receipt commits. A changed caller account is rejected rather than overwritten.

If the subsequent Trade Plan append conflicts, reload and call `execute_directive` again. The
durable receipt restores an exact pre-execution account to its recorded post-state or recognizes
an already-applied outcome; it never reapplies the fill. A later account already containing that
outcome is preserved. Trade Plan appends exactly one link with the original execution timestamp,
even when reconciliation occurs on another day. Receipts later than `as_of` are unavailable.
Rejections follow the same permanent order identity and reconciliation rules.

An unfinished claim after an execution, storage failure or process interruption has an unknown
result and raises `ExecutionReconciliationError`. It is never expired, deleted, taken over or
blindly re-executed. Preserve the claim and inspect authoritative execution/accounting evidence
before a separately reviewed operational recovery; this change adds no claim-reset or arbitrary
state-edit command. An in-memory journal exists only for deterministic tests/research. This
contract covers the existing deterministic execution engine; it introduces no external broker
side effects or new risk authority. Callers retain ownership of their account's single-writer
execution scope; conflicting account projections fail closed.

## Deliberate V1 limits

SPEC-010 has no AI Brain, signal generation, natural-language interpretation, Kelly sizing,
leverage, direct US execution, UI, broker connectivity or new intraday engine. Profit target
selection and consumption are deterministic from configured policies and recorded execution
attempts; richer partial-fill attribution remains future work.
