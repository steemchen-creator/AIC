# SPEC-010 — Multi-Horizon Trade Plan and Swing Management Foundation

Version: 1.0  
Status: CHAIRMAN AUTHORIZED / READY FOR GOVERNED ENGINEERING  
Owner: Chief Investment Architect  
Execution authority: `CHAIRMAN-DELEGATION-AIC-STANDARD-WORK-V1`

## 1. Purpose

SPEC-010 establishes the first governed trade-plan layer for AIC.

The system already has deterministic portfolio, execution, risk, forward-paper, shadow-account,
ETF/index and CNY multi-asset foundations. SPEC-010 adds the missing layer between an investment
decision and those execution/risk systems: an explicit, versioned, auditable Trade Plan with a
declared investment horizon, trading style, entry/scale/reduce/exit intent, risk conditions,
expiry and outcome/adherence evidence.

This SPEC does **not** add an AI investment brain or a signal-generation strategy. It provides
the deterministic foundation that future strategy/AI components must use.

## 2. Baseline and dependencies

Implementation must preserve and reuse the existing foundations rather than duplicate them:

- existing Portfolio accounting and deterministic backtest foundation;
- A-share execution and risk rules;
- forward paper trading and Champion portfolio;
- isolated Shadow portfolios;
- Equity + CN-listed ETF mixed CNY portfolios;
- CN-listed Nasdaq QDII ETF exposure;
- non-tradable Index reference identity and Benchmark usage;
- instrument-specific T+0/T+1, lot, price-limit, trading-status and fee/tax rules;
- PIT / no-lookahead data semantics;
- existing branch protection, exact-HEAD CI and DEV-GOV workflow.

Existing risk/execution systems remain authoritative. A Trade Plan can request an action but
cannot bypass an execution, settlement, tradability, cash, exposure, concentration, turnover,
lot, price-limit or other risk rejection.

## 3. Scope

SPEC-010 must implement:

1. multi-horizon taxonomy;
2. trading-style taxonomy;
3. `TradePlan` aggregate and append-only revision history;
4. deterministic Trade Plan lifecycle;
5. one active Trade Plan per `(portfolio, instrument)` in V1;
6. explicit entry / scale-in / hold / reduce / full-exit directives;
7. hard stop, profit target, trailing stop, time stop, thesis invalidation and plan expiry;
8. PIT-safe plan evaluation and next-eligible-open execution semantics;
9. anti-loss-relabel controls;
10. integration with the existing execution/risk path;
11. Equity + domestic ETF + CN-listed Nasdaq QDII ETF compatibility;
12. Index reference non-tradability preservation;
13. Champion and Shadow account isolation;
14. Trade Plan outcome, adherence and performance evidence;
15. PostgreSQL persistence, migration, in-memory parity, documentation and deterministic tests.

## 4. Explicit non-scope

SPEC-010 must not introduce:

- AI Brain, autonomous stock selection or LLM-generated investment opinions;
- Opportunity Radar;
- strategy research/promotion pipeline changes;
- Kelly sizing;
- leverage or borrowing;
- direct US-market execution;
- USD cash accounting or FX;
- new market-data providers;
- broker/live-trading permissions;
- unrestricted auto-trading;
- memory retrieval, lesson promotion or Memory Vault changes;
- governance redesign;
- desktop/UI product work;
- a new intraday/tick market-data engine;
- high-frequency trading;
- automatic natural-language interpretation of thesis text.

Future components may consume this foundation, but they are not part of this SPEC.

## 5. Investment-horizon taxonomy

The domain must define the following horizon values:

```text
T
SHORT
MEDIUM_SHORT
MEDIUM
MEDIUM_LONG
LONG
```

Semantics:

- `T`: same-session / very-short holding intent. SPEC-010 records the horizon and can support
  eligible product-level T+0 execution, but does not add a new intraday signal/data engine.
- `SHORT`: short holding window.
- `MEDIUM_SHORT`: between short and medium.
- `MEDIUM`: medium holding window.
- `MEDIUM_LONG`: between medium and long.
- `LONG`: long holding window.

The system must not silently infer a horizon from later price behavior.

A horizon is a pre-trade/activation decision and becomes immutable after activation.
A later adverse move must not be converted into a longer horizon merely to avoid recognizing
a stop, exit or failed thesis.

## 6. Trading-style taxonomy

The domain must define:

```text
SWING
TREND
VALUE
EVENT
INDEX
MEAN_REVERSION
OTHER
```

The style is descriptive policy metadata for the plan. It is not an executable strategy by
itself.

`INDEX` style does not make an Index reference instrument tradable. Actual executable
instruments remain those already supported by the execution foundation.

Style becomes immutable after plan activation for the same anti-relabel reason as horizon.

## 7. TradePlan identity and lifecycle

A `TradePlan` must have stable identity and belong to exactly one Portfolio and one executable
Instrument.

Minimum lifecycle:

```text
DRAFT
ACTIVE
COMPLETED
CANCELLED
EXPIRED
INVALIDATED
```

Rules:

- `DRAFT` may be edited before activation.
- activation validates all required fields and creates immutable version 1 evidence;
- only `ACTIVE` plans may emit executable directives;
- terminal states cannot reactivate;
- a successor requires a new `plan_id`;
- historical plans and revisions are never silently rewritten or deleted;
- only one `ACTIVE` plan may exist for the same `(portfolio_id, instrument_id)` in V1;
- database and application layers must both enforce this invariant.

## 8. Required TradePlan fields

The implementation may choose names consistent with repository conventions, but the domain
must preserve at least:

- `plan_id`;
- `portfolio_id`;
- executable instrument identity;
- `horizon`;
- `style`;
- lifecycle status;
- plan creation time;
- activation/effective time;
- optional expiry time;
- human-readable thesis;
- optional structured thesis-invalidation policy/reference;
- initial position intent or target quantity;
- stop policy;
- profit-target policy;
- trailing-stop policy;
- time-stop policy;
- revision/version number;
- policy/version metadata;
- provenance/audit timestamps.

Text thesis is audit/documentation data only. Deterministic code must not parse prose and
pretend it is a trading signal.

## 9. Append-only revision model

All post-activation permitted changes must create a new immutable revision.

A revision must record:

- plan id;
- monotonically increasing version;
- effective/recorded timestamp;
- change reason;
- changed fields or a complete canonical snapshot;
- actor/source metadata where available.

Historical revisions remain queryable.

Horizon and style cannot be modified after activation.

Stop/target parameters may be amended only through a revision with an explicit reason.
Original values and prior outcomes remain preserved for later adherence analysis.

No update may rewrite prior P&L, trigger history, decision evidence or the original thesis.

## 10. Plan directives

SPEC-010 must model explicit plan directives/actions:

```text
ENTRY
SCALE_IN
HOLD
REDUCE
EXIT
```

Rules:

- `ENTRY` opens the first position under the plan.
- `SCALE_IN` increases exposure.
- `HOLD` records a deliberate no-order decision.
- `REDUCE` decreases but does not fully close the position.
- `EXIT` requests a full exit.
- executable directives must reference the exact Trade Plan revision that produced them;
- directives must be idempotently identifiable;
- `HOLD` must not create a fake order/fill.

V1 sizing must use explicit deterministic quantities/target quantities. Kelly, probabilistic
sizing and AI sizing are deferred.

## 11. Stop, target and expiry policies

The Trade Plan foundation must support:

### Hard stop
A deterministic price threshold which, when validly observed, can produce an exit/reduce
directive according to the plan.

### Profit target
One or more deterministic target levels. A target may request reduction or full exit.

### Trailing stop
A deterministic rule based on observed favorable price progression and an explicit trailing
distance/percentage policy. The high-water/anchor state must be auditably stored and PIT-safe.

### Time stop
A deterministic deadline/holding-time rule.

### Thesis invalidation
A structured explicit invalidation event or policy reference. Natural-language thesis text
must not be parsed automatically in this SPEC.

### Expiry
An `ACTIVE` plan reaching expiry without an earlier terminal transition becomes `EXPIRED`
according to deterministic clock/session semantics and cannot be reactivated.

## 12. No-lookahead and execution timing

All Trade Plan evaluation must obey existing PIT rules.

For daily/close-based evaluation in V1:

1. only observations available at the decision `as_of` may be used;
2. a trigger observed from trading day/session `D` must not receive a fill earlier than the
   next eligible execution opportunity permitted by the existing execution/calendar rules;
3. ordinary daily-bar decisions therefore execute no earlier than the next eligible market
   open/session;
4. future bars, future execution profiles, future trading status, future price-limit evidence
   and future revisions must be unavailable;
5. event timestamps, observation timestamps and execution timestamps must remain distinct.

If an instrument supports product-level T+0, that fact continues to be enforced by the
existing execution profile. SPEC-010 does not invent intraday data that does not exist.

## 13. Anti-loss-relabel invariant

The implementation must explicitly prevent post-hoc loss avoidance through plan relabeling.

At minimum:

- active-plan `horizon` is immutable;
- active-plan `style` is immutable;
- terminal-plan identity/history is immutable;
- a losing SHORT plan cannot become MEDIUM/LONG under the same active plan;
- a successor plan requires the prior plan to reach a terminal state and must have a new id;
- successor creation does not change the predecessor's performance/adherence statistics;
- attempts to mutate protected fields return stable domain/application errors and have
  regression tests.

This invariant is a hard requirement.

## 14. Execution and risk integration

Trade Plan code must not implement a parallel broker/execution engine.

Architecture:

```text
TradePlan Domain
      |
TradePlan Application Service
      |
existing Order / Execution / Risk interfaces
      |
existing Paper / Shadow portfolio execution
```

Every executable directive must flow through the existing authoritative order/execution/risk
chain.

A plan must remain `ACTIVE` or transition according to explicit policy when an order is
rejected; it must not pretend a rejected order was executed.

Execution evidence must link:

- `plan_id`;
- plan revision/version;
- directive id/type;
- existing order id;
- existing fill/execution ids where applicable;
- rejection reason where applicable.

## 15. Supported instruments and asset boundaries

V1 executable Trade Plans must support:

- A-share Equity;
- domestic CN-listed ETF;
- CN-listed Nasdaq QDII ETF.

Existing currency/account boundary remains CNY.

Existing non-tradable reference Index remains non-tradable. Attempting to activate or execute
a Trade Plan against a reference Index must fail closed with a stable reason.

No direct US instrument, USD account or FX support is added.

## 16. Champion and Shadow portfolios

Trade Plans must work with the existing portfolio/account abstraction so that:

- Champion plans affect only the Champion portfolio;
- each Shadow member has isolated plans, directives, orders, fills and outcomes;
- no plan or revision leaks across accounts;
- identical instruments in different portfolios may have independent active plans.

The V1 uniqueness rule is therefore `(portfolio, instrument)`, not global instrument.

## 17. Outcome and adherence evidence

When a plan becomes terminal, the system must be able to produce a deterministic outcome
record including, where available:

- plan id;
- portfolio/instrument;
- horizon/style;
- activation and terminal timestamps;
- entry/average entry evidence;
- exit/remaining position evidence;
- realized P&L attributable through existing execution data;
- holding duration;
- terminal reason;
- stop/target/expiry/thesis-invalidated indicators;
- number of scale-ins/reductions;
- rejected directives/orders;
- whether actual actions adhered to the current plan revision;
- revision count.

This is measurement infrastructure only. SPEC-010 does not rank or promote strategies.

## 18. Persistence and migration

Add application-owned repository ports and PostgreSQL adapters for Trade Plan state.

Persistence must provide:

- stable identities;
- append-only revisions;
- active-plan uniqueness;
- deterministic ordering;
- PIT/as-of reads where relevant;
- idempotent writes;
- explicit conflict behavior rather than silent overwrite;
- migration upgrade and downgrade;
- PostgreSQL and in-memory parity.

Do not encode provider-specific fields in the Trade Plan domain.

## 19. Application services

Provide narrow services for at least:

- create draft plan;
- activate plan;
- revise permitted fields;
- evaluate active plan at `as_of`;
- record thesis invalidation;
- create/record plan directive;
- send executable directives through existing execution/risk;
- transition plan to terminal state;
- query current active plan;
- query plan history/revisions;
- build outcome/adherence record.

Service boundaries must remain testable without network access.

## 20. Determinism and failure behavior

The system must fail closed on:

- unknown horizon/style;
- missing required activation fields;
- duplicate active plan for portfolio+instrument;
- invalid terminal transition;
- protected-field mutation;
- future/unavailable PIT evidence;
- non-tradable Index;
- unsupported asset/currency;
- invalid quantities/prices;
- invalid stop/target/trailing values;
- stale revision/version conflict;
- execution/risk rejection.

Use stable error/reason identifiers suitable for tests and audit.

## 21. Architecture boundaries

Preserve Clean Architecture:

- Domain: pure Trade Plan entities, value objects, policies and transitions;
- Application: use cases, repository/execution ports and orchestration;
- Infrastructure: PostgreSQL adapters only;
- Provider/Data Foundation: unchanged unless a minimal existing interface adaptation is
  strictly required;
- UI: unchanged.

Domain must not import SQL, HTTP, Tushare, WPF, GitHub or LLM code.

Application must not import concrete database/provider implementations.

## 22. Required tests

At minimum add deterministic tests covering:

1. every horizon and style enum;
2. valid lifecycle transitions;
3. invalid lifecycle transitions;
4. one active plan per portfolio+instrument;
5. independent plans for the same instrument in different portfolios;
6. activation and immutable version 1;
7. append-only revisions;
8. horizon mutation rejection after activation;
9. style mutation rejection after activation;
10. scale-in;
11. hold with no fake order;
12. reduce;
13. full exit;
14. hard stop;
15. profit target;
16. trailing-stop anchor/high-water behavior;
17. time stop;
18. expiry;
19. thesis-invalidation event;
20. daily `D` decision cannot fill before next eligible execution opportunity;
21. future data/revision is invisible to earlier `as_of`;
22. execution/risk rejection is preserved and not counted as a fill;
23. Equity plan E2E;
24. domestic ETF plan E2E;
25. Nasdaq-QDII ETF plan E2E;
26. reference Index plan rejection;
27. Champion/Shadow isolation;
28. terminal outcome/adherence record;
29. migration upgrade/downgrade;
30. PostgreSQL and in-memory repository parity;
31. regression of existing portfolio/execution/risk behavior.

## 23. Quality gates

The implementation PR must pass, at the exact reviewed HEAD:

- Governance baseline;
- Backend tests with PostgreSQL 17 where required;
- Desktop build;
- AIC Development Governance Gate;
- Ruff;
- strict mypy;
- migration round-trip;
- repository architecture tests;
- `git diff --check`.

Repository coverage must remain above the existing project gate. New Trade Plan domain/application
code must have proportionate branch coverage and explicit negative-path tests.

## 24. Documentation deliverables

Update as appropriate in the same PR:

- `README.md`;
- `CHANGELOG.md`;
- architecture documentation;
- Trade Plan / multi-horizon design documentation;
- migration/schema documentation;
- technical debt registry for any accepted limitation;
- ADR only if implementation introduces a material architectural decision not already
  authorized by this SPEC.

Do not rewrite historical SPEC/review evidence.

## 25. Acceptance criteria

SPEC-010 is acceptable only if all of the following are demonstrated at one exact PR HEAD:

- a plan is explicitly classified by horizon and style before activation;
- horizon/style cannot be rewritten after activation;
- one active plan per portfolio+instrument is enforced;
- entry, scale-in, hold, reduce and exit are all represented deterministically;
- stops, targets, trailing, time and expiry behavior are testable and audit-linked;
- next-open/no-lookahead behavior is proven;
- all executable actions traverse existing risk/execution;
- Equity, domestic ETF and Nasdaq-QDII ETF work without breaking CNY accounting;
- Index remains non-tradable;
- Champion/Shadow plans remain isolated;
- revisions remain immutable;
- outcome/adherence evidence can be reproduced from stored state/execution evidence;
- all required CI and quality gates pass.

## 26. Engineering stop condition

Codex/CTO must:

1. work only on the registered SPEC-010 target branch;
2. create/keep a Draft PR;
3. implement the smallest coherent solution satisfying this SPEC;
4. commit and push focused checkpoints;
5. produce `REVIEW-SPEC010.md` with requirement traceability and exact test evidence;
6. attach the Draft PR through the DEV-GOV orchestrator;
7. stop after exact-HEAD CI and durable state are reported;
8. not mark Ready, merge, change governance policy or start SPEC-011.

Chief Investment Architect review binds to the exact PR HEAD SHA.
Any implementation HEAD change invalidates prior Architecture Approval.
