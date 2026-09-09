# REVIEW-SPEC010

## 1. Executive summary

SPEC-010 is implemented as a deterministic Trade Plan foundation between investment decisions and
the existing authoritative execution/risk chain. It adds no signal generator or AI investment
behavior. Plans are classified before activation, retain append-only policy and trailing-anchor
revisions, enforce one active plan per portfolio/instrument, produce revision-bound directives,
and retain outcome/adherence evidence.

## 2. Git and governance binding

- Work Item: `SPEC-010`
- Engineering Task: GitHub Issue #18
- Base `main`: `ec09fa568f0513d9a0a9548044921d09edaf213c`
- Branch: `feature/spec-010-multi-horizon-trade-plan`
- Execution identity: `aic-codex-cto`
- Execution authorization: `CHAIRMAN-DELEGATION-AIC-STANDARD-WORK-V1`
- Specification Git-content SHA-256:
  `b786de248003685aa91be001ad7e17101c4312d71d676225c9f2537e687db403`
- `CODEX_STARTED`: protected orchestrator run `34305536507`, succeeded; durable state moved to
  `IMPLEMENTING` before implementation.
- Final commit, Draft PR, exact HEAD and exact-HEAD CI are reported externally after this file is
  committed. No evidence-only or self-referential commit is created.

## 3. Architecture

```text
Trade Plan domain (pure policy, lifecycle, immutable evidence)
          ^
Trade Plan application (use cases + owned ports + PIT next-open lock)
          ^                                  ^
PostgreSQL / in-memory adapters       existing AShareExecutionService
                                             |
                               existing execution / settlement / risk
```

The application owns `TradePlanRepository`, `NextEligibleOpenCalendar` and
`AuthoritativeExecution` protocols. `AShareExecutionService` structurally satisfies the execution
port; Trade Plan does not calculate a fill or bypass the existing order/risk chain. SQL/Pydantic
remain in Infrastructure. No ADR was added because this structure is explicitly authorized by
SPEC-010 and does not change an earlier architectural decision.

## 4. Requirement traceability

| SPEC-010 requirement | Implementation/evidence |
|---|---|
| Horizon taxonomy | Exact six-value `InvestmentHorizon`; enum/unknown tests |
| Trading-style taxonomy | Exact seven-value `TradingStyle`; enum/unknown tests |
| Aggregate/lifecycle | Immutable `TradePlan`, explicit DRAFT/ACTIVE/terminal transitions |
| Append-only revisions | Complete `TradePlanRevision` snapshots; persistence prefix validation |
| One active per pair | Application check, in-memory check, PostgreSQL partial unique index |
| ENTRY/SCALE_IN/HOLD/REDUCE/EXIT | Stable revision-bound directives; BUY/SELL gateway tests; HOLD no order |
| Stops/targets | Hard, ordered profit, trailing anchor, time, invalidation and expiry tests |
| PIT/no-lookahead | Availability checks and existing PIT calendar-based next-open adapter |
| Anti-loss-relabel | Active horizon/style and terminal history immutable; successor requires new id |
| Execution/risk authority | Existing order/risk service delegation; links retain fills and rejects |
| Equity / ETF / Nasdaq-QDII | CN Equity and listed ETF identities; existing ETF profile remains authoritative |
| Index fail closed | `INDEX` identity rejected before plan persistence/activation |
| Champion/Shadow isolation | Portfolio is part of active uniqueness and every evidence record |
| Outcome/adherence | Terminal trigger/count/rejection/adherence/source-link evidence |
| PostgreSQL/in-memory parity | Same repository contract and parity round-trip test |
| Migration | Reversible `20260909_0014`, normalized evidence and active partial index |
| Clean Architecture | Dedicated architecture regression test |

## 5. Deterministic test mapping

The added tests cover all required categories:

1. every horizon/style and unknown values;
2. valid and invalid lifecycle transitions;
3. active-plan uniqueness and cross-portfolio independence;
4. activation/version 1, draft editing and activation freeze;
5. append-only revisions, stale conflicts and protected-field rejection;
6. all five directive types, HOLD no-order behavior and stable execution links;
7. hard stop, ordered profit target, trailing high-water/drawdown, time stop, expiry and structured
   thesis invalidation;
8. future observation rejection and next-eligible-open execution lock;
9. risk rejection preservation without a fill or false terminal success;
10. Equity and CN-listed ETF compatibility, reference Index rejection and unsupported market
    boundary;
11. Champion/Shadow portfolio key isolation;
12. terminal outcome/adherence and idempotent materialization;
13. projection serialization, PostgreSQL parity/idempotency/conflicts and corruption handling;
14. migration 0013 to 0014 and base to head round-trip;
15. existing architecture plus portfolio/execution/risk regression in the full suite.

## 6. Persistence and migration

`trade_plans` stores an atomic current recovery projection. Normalized
`trade_plan_revisions`, `trade_plan_directives`, `trade_plan_execution_evidence` and
`trade_plan_outcomes` retain queryable append-only facts. Stable identities are insert-or-verify;
conflicting reuse fails. Foreign keys preserve plan/revision/directive linkage. Downgrade removes
only SPEC-010 tables and is destructive to their history, so production use requires backup and
explicit authorization.

## 7. Outcome and adherence semantics

Trade Plan links plan, revision and directive identities to existing order/fill or stable rejection
evidence. Terminal outcome values are supplied from the authoritative portfolio/execution ledger;
Trade Plan does not become a second P&L authority. Adherence is false while any executable
directive lacks a recorded fill. Rejected orders remain visible and do not pretend execution.

## 8. Scope confirmation

Implemented: taxonomy, lifecycle, revisions, directive model, stop/target/invalidation/expiry,
PIT/next-open lock, anti-relabel, execution links, CNY listed Equity/ETF boundary, Index rejection,
portfolio isolation, outcome/adherence, dual persistence, migration, tests and documentation.

Not implemented or modified: AI Brain, Opportunity Radar, signal generation, natural-language
thesis parsing, Kelly sizing, leverage, borrowing, direct US execution, USD/FX, broker/live trading,
new market-data providers, intraday engine, UI, governance policy, branch protection or merge
controls. SPEC-011 and later work are not started.

## 9. Validation evidence

Before final push, Engineering runs:

- `pytest --cov --cov-report=term-missing --cov-report=json:tmp/coverage.json` in PostgreSQL 17 CI;
- `ruff check apps/backend/src apps/backend/tests`;
- strict `mypy` from repository configuration;
- architecture tests;
- migration 0013 to 0014 and base to head round-trip;
- `git diff --check`;
- .NET Release build through required CI.

Pre-commit evidence on Python 3.12.14:

- focused Trade Plan suite: `24 passed`;
- focused new domain/application branch coverage: `95.06%`;
- all non-database backend tests: `876 passed`, repository branch coverage `92.53%`;
- architecture suite: `34 passed`;
- Ruff and strict mypy: passed (`147 source files`).

This Windows host has no PostgreSQL service, Docker executable or .NET SDK. The unmodified
required CI jobs supply PostgreSQL 17 and the .NET 8 SDK, run the complete suite plus migration
round-trip, and build the desktop at the exact PR HEAD. Exact complete counts and GitHub check
conclusions bind to the external final HEAD attestation rather than being edited into a later
commit.

## 10. Accepted limitations / debt

- No intraday observation engine; `T` is recorded intent under existing data capabilities.
- Ordered target evaluation has no strategy-specific consumed-target state in V1.
- Outcome monetary inputs require an explicit projection from existing authoritative ledgers.
- No US/USD/FX, leverage, Kelly, AI or UI behavior.

These are recorded in `docs/project/TECHNICAL_DEBT.md` and do not weaken required invariants.

## 11. Rollback

Code rollback is the normal PR revert path. Migration downgrade from `20260909_0014` to
`20260906_0013` drops only SPEC-010 tables, but deletes their evidence and therefore requires
backup plus explicit operational authorization. No migration or state mutation is automatic.

## 12. Engineering recommendation

`APPROVED_CANDIDATE_FOR_ARCHITECTURE_REVIEW` after the external exact-HEAD required checks pass.
Engineering does not self-approve, mark Ready, merge or enable Auto Merge.
