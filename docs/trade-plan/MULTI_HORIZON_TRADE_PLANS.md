# Multi-Horizon Trade Plan Foundation

SPEC-010 adds an explicit planning layer between an investment decision and the existing
authoritative execution/risk foundation. It does not generate investment opinions. A caller must
provide the thesis, classification, deterministic quantity and policies before activation.

## Taxonomy and lifecycle

Investment horizons are `T`, `SHORT`, `MEDIUM_SHORT`, `MEDIUM`, `MEDIUM_LONG` and `LONG`.
Trading styles are `SWING`, `TREND`, `VALUE`, `EVENT`, `INDEX`, `MEAN_REVERSION` and `OTHER`.
Both are descriptive plan policy, not strategies. They are editable while a plan is `DRAFT` and
immutable after activation.

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

Terminal outcome materialization links stored revisions, directives and execution evidence with
caller-supplied values derived from the authoritative portfolio/execution ledger. It reports
holding duration, realized P&L, remaining quantity, trigger flags, scale/reduce/rejection counts
and adherence. It is measurement evidence only and does not rank strategies.

## PIT and next eligible open

`PlanObservation` keeps event and availability times distinct. Evaluation rejects any event or
availability later than `as_of`. `PointInTimeNextOpenCalendar` reads only the existing PIT trading
calendar and schedules a daily-bar directive no earlier than the next known eligible market open.
Execution rechecks that time and then lets the existing execution service re-evaluate current
calendar, tradability, price-limit, settlement and risk evidence. A future revision or bar is not
visible to an earlier evaluation.

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

## Deliberate V1 limits

SPEC-010 has no AI Brain, signal generation, natural-language interpretation, Kelly sizing,
leverage, direct US execution, UI, broker connectivity or new intraday engine. Profit target
selection is deterministic from the ordered configured levels; strategy-specific target-consumed
policy and richer partial-fill attribution remain future work.
