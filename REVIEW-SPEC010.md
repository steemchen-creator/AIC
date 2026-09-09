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

## 10. Deliberate V1 boundaries

- No intraday observation engine; `T` is recorded intent under existing data capabilities.
- Ordered target evaluation has no strategy-specific consumed-target state in V1.
- Outcome monetary inputs require an explicit projection from existing authoritative ledgers.
- No US/USD/FX, leverage, Kelly, AI or UI behavior.

These are authorized SPEC-010 non-scope or future extensions, not newly accepted technical debt.
No technical-debt registry entry is introduced by this PR.

## 11. Rollback

Code rollback is the normal PR revert path. Migration downgrade from `20260909_0014` to
`20260906_0013` drops only SPEC-010 tables, but deletes their evidence and therefore requires
backup plus explicit operational authorization. No migration or state mutation is automatic.

## 12. Engineering recommendation

`APPROVED_CANDIDATE_FOR_ARCHITECTURE_REVIEW` after the external exact-HEAD required checks pass.
Engineering does not self-approve, mark Ready, merge or enable Auto Merge.

## 13. Architecture Review remediation (2026-09-10)

This section records Engineering's fixes for the five blocking findings in
[Architecture Review 5156808778](https://github.com/steemchen-creator/AIC/pull/19#pullrequestreview-5156808778),
reaffirmed by
[Architecture Review 5156995482](https://github.com/steemchen-creator/AIC/pull/19#pullrequestreview-5156995482)
against `ae12e925fb5094e4274c9140a306325cd10a5334`. Earlier evidence above remains historical;
this section supersedes the deferred target-consumption statement in section 10. Independent
Architecture re-review is still required on the new exact HEAD; this is not approval.

| Blocker | Implemented boundary | Regression evidence |
| --- | --- | --- |
| PIT / revision binding and invalidation atomicity | All directive paths select a revision with both effective and recorded timestamps visible at `as_of`. Terminal validation and calendar preparation precede one aggregate save. | All five manual directive kinds, future/late-recorded revisions, stale invalidation with and without an older policy, and calendar failure leaving no partial high-water or expiry evidence. |
| Position semantics and repeated triggers | Account ownership and actual remaining position govern ENTRY, SCALE_IN, strictly partial REDUCE and full EXIT. Persisted canonical policy keys consume automatic stop/target attempts across observations and restarts. | Ten position cases, caller-hint/account mismatch, filled/rejected stop and target replay, independent target levels, equivalent policy amendments, legacy payloads, and historical decisions before future fills. |
| Concurrent PostgreSQL lost updates | Lock the current plan row before validating append-only prefixes; hold the lock through the atomic projection and normalized evidence writes. Reject stale appends explicitly. | Three concurrent cases for revisions, directives and executions observe real PostgreSQL lock waits, reject the losing stale writer, then reload/append and verify both writers' evidence and normalized counts. |
| Terminal outcome frozen before EXIT resolves | Block materialization while any executable directive lacks fill or rejection evidence. Completed outcomes remain immutable. | EXPIRED and INVALIDATED pending EXIT cases both fail without writes, then include subsequent fill/rejection evidence and correct adherence. |
| Draft instrument identity | Instrument and portfolio are immutable for the full `plan_id` lifetime at service and repository boundaries. | Reject draft instrument/portfolio replacement, retain valid draft taxonomy/thesis/policy editing, and test the PostgreSQL boundary. |

The fix adds 36 application regression cases and five PostgreSQL cases. The automatic policy
identity excludes revision number, observation time and trailing high-water so incidental updates
cannot rearm the same action. Fills and rejections both consume an attempt; there is no automatic
retry after rejection. A changed price/distance/deadline, action or quantity is a different explicit
policy. Legacy targets lacking a unique policy key are consumed conservatively when their
revision/action/quantity match, avoiding duplicate execution of ambiguous historical targets.

PostgreSQL writers now serialize on one plan row. Stale callers receive `IDENTITY_CONFLICT` and
must reload and explicitly append; no automatic merge or unbounded retry is introduced. The
optional trigger key fits existing directive JSON, defaults safely for old records, and is omitted
from unchanged legacy normalized payloads. No DDL change, extra migration, evidence rewrite,
execution/risk bypass or governance change is required. Rollback remains the existing code-revert
procedure; migration 0014 and its destructive-downgrade precautions are unchanged.

Local validation on Python 3.12.14:

- `python -m pytest --ignore=apps/backend/tests/infrastructure --cov --cov-report=json:tmp/spec010-review-local-coverage.json --cov-report=term -q`:
  `964 passed`, total branch-aware coverage `92.61%` (includes 60 Trade Plan and 34 architecture cases).
- `python -m ruff check apps/backend/src apps/backend/tests`: passed.
- `python -m mypy`: strict configuration passed, `147 source files`.
- `git diff --check`: passed before commit.

The unchanged exact-HEAD CI runs the full PostgreSQL 17 suite, including concurrent writes,
migration 0013/0014 and base/head round-trips, architecture tests, coverage enforcement, Ruff,
strict mypy, Governance Gate and desktop build. Its final run URL and complete counts are recorded
in the PR description after execution, without creating a later untested documentation HEAD.
PR #19 remains Draft; Engineering does not self-approve, merge or start SPEC-011.

## 14. Cross-aggregate execution-idempotency remediation (2026-09-10)

The follow-up blocking finding supplied for `5fed0265eea54352848c514300a9e6fd69541e34`
identified a financial retry gap: authoritative execution could succeed before the Trade Plan
append failed with `IDENTITY_CONFLICT`. A later SCALE_IN or REDUCE could execute again without
the missing link. The original five fixes remain in place; this section addresses that one
additional blocker and is an Engineering record, not independent approval.

### Contract and transaction boundaries

`IdempotentExecutionService` implements the application-owned authoritative execution port around
the unchanged `AShareExecutionService`. `ExecutionJournal` is an application-owned storage port;
its production PostgreSQL adapter persists permanent claims keyed by deterministic order ID.
Migration `20260910_0015` introduces only `execution_order_claims` and its portfolio/time index.

1. A unique order claim commits before calling the existing execution/risk authority. A duplicate
   caller reconciles a completed receipt or fails closed while the claim is unresolved. Request
   identity includes account, instrument, side, quantity and requested price.
2. The existing deterministic authority runs against a detached account/settlement state. Its
   order, fill, risk decision, cash ledger and settlement results retain their original identities.
3. Completion verifies claim ownership under a row lock and commits one immutable outcome and
   recovery snapshot. Only then is the caller's account projection published. A concurrent caller
   account mutation is rejected instead of overwritten.
4. Trade Plan independently appends its link. If this transaction conflicts, the next invocation
   reloads the aggregate and reconciles the durable receipt before position validation. It never
   calls the financial engine a second time and uses the original execution timestamp.
5. Replay restores an exact pre-execution account or recognizes an applied outcome. Later account
   state containing that outcome is preserved. Cross-account requests, changed order intents,
   unknown account projections and future outcomes fail closed.

This is a durable execution-claim mechanism, not an in-memory deduplication cache or a catch-and-
retry loop. Rejected orders also retain their identity and risk outcome. A claim interrupted before
receipt completion remains unresolved permanently: no expiration, takeover or reset is introduced.
Such uncertainty requires separate operational reconciliation against authoritative evidence,
never another financial attempt under the same ID. The journal does not change the risk policy,
create a broker integration or replace the existing account's single-writer ownership contract.

### Regression evidence

- Six PostgreSQL cases cover SCALE_IN, REDUCE and EXIT, each with successful and rejected execution.
  They use the real A-share execution/risk service, commit a concurrent Trade Plan HOLD after the
  financial operation returns, and require the link save to fail with `IDENTITY_CONFLICT`.
- New services and database connections then reconstruct the pre-execution account, restore the
  durable result, and append exactly one link. A second replay of the already-applied account
  remains unchanged. Tests compare full cash/position/settlement/counter/outcome snapshots, original
  order/fill/timestamp identities, normalized link/risk counts and the unchanged completed receipt.
  The restarted authority raises if called, proving reconciliation performs no financial retry.
- A PostgreSQL receipt-write failure leaves an unresolved claim that blocks restart execution;
  the caller account is not published before receipt commit.
- PostgreSQL claim races have one winner; claim ownership, receipt immutability and corrupt-read
  rejection are checked. Migration 0014/0015 is round-tripped twice; the existing suite retains
  the full base/head rebuild.
- Three application cases exercise receipt serialization, request/account/PIT guards, later-state
  preservation and same-order concurrent callers, including changed account state during execution.

Local validation passed: full non-database suite `967 passed` with `92.20%` branch-aware coverage,
Ruff, strict mypy (150 source files), 34 architecture tests and `git diff --check`.
New journal modules are explicitly included in coverage. PostgreSQL
17, all migrations, full backend coverage and .NET are verified by the unchanged exact-HEAD CI;
the final run/counts are attached to the PR description without a subsequent untested HEAD.

### Deployment and rollback

Apply migration 0015 before composing TradePlanService with IdempotentExecutionService and
PostgreSQLExecutionJournal. In-memory storage is limited to tests/research. Completed receipts
and unresolved claims are safety-critical audit history and must not be reset to retry a directive.
Revert code through review; stopping execution, backing up this journal and explicit operational
authorization are prerequisites for a production downgrade because it removes deduplication
evidence. No governance code, automation/dev-state or SPEC-011 work is included. Keep PR #19 Draft
and require independent review of the final exact HEAD; no Ready, self-approval or merge action.
