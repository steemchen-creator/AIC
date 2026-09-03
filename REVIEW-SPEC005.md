# SPEC-005 Architecture Review Evidence

## 1. Executive Summary

SPEC-005 建立了确定性、可审计、PIT-only 的多持仓 Portfolio/Backtest 基础。相同 Run、
PIT 数据、订单意图和 policy versions 产生相同 fills、cash ledger、positions、NAV、result
和 audit event IDs。候选结论：`B. APPROVED CANDIDATE WITH NON-BLOCKING DEBT`。

## 2. Git / Branch / PR Status

- Branch: `feature/backtest-portfolio-foundation`
- Base: `main`
- Draft PR: 完成 Commit/Push 后创建；不得 Merge。
- Final SHA/PR Head/CI 采用外部 immutable attestation，避免 evidence-only commit 循环。

## 3. Scope Confirmation

已实现规格要求的会计、确定性日线回放、PIT 数据入口、审计、PostgreSQL 和测试。
未实现 AI、Shadow、Memory、Governance、正式 Strategy、Risk Engine、Live Trading、UI、
分钟/Tick、杠杆、做空、partial fill 或完整 corporate-action portfolio accounting。

## 4. Architecture Diff

```text
domain/portfolio -> pure values, accounting, policies
application/backtest.py -> PIT-only deterministic orchestration
application/ports/backtest.py -> owned persistence contract
infrastructure/backtest_persistence.py -> PostgreSQL adapter
migration 0008 -> normalized evidence tables
```

Domain 仅依赖标准库及既有 canonical InstrumentIdentity。Application 不依赖 Infrastructure、
Provider、HTTP 或 UI。Concrete SQLAlchemy 仅在 Infrastructure。

## 5. Domain Models

`PortfolioId`、`BacktestRunId`、`OrderId`、`FillId`、`PositionKey`、`Money`、`Quantity`、
`Price` 均有 value semantics。金额、价格、数量、成本和 PnL 使用 Decimal；V1 仅支持 CNY。

## 6. Backtest Run

`BacktestRun` 保存 run/portfolio identity、aware start/end/created_at、initial capital 以及
data/fee/slippage/execution policy versions。执行前严格比对注入 policy versions。

## 7. Portfolio Model

`PortfolioAccount` 支持任意正 initial capital、多 instrument positions、cash、realized PnL、
immutable daily snapshots。CNY 500,000 只用于固定 E2E，未写死在实现中。

## 8. Cash Ledger

初始资本、买卖结算、费用和税均生成 stable ID、aware timestamp、signed amount、
balance-after 和 source fill/run。现金不是不可追溯的单一可变值。

## 9. Position Accounting

BUY 按 notional+cost 更新数量和加权平均成本；SELL 降低数量并保留剩余平均成本。
数量不能为负，sell 超持仓显式失败。

## 10. Order Lifecycle

支持 CREATED → ACCEPTED → FILLED，以及 CREATED/ACCEPTED → CANCELLED/REJECTED。
非法转换显式 `INVALID_ORDER`。V1 仅 full fill，不伪支持 partial fill。

## 11. Fill Model

Fill 与 Order 分离且 immutable，记录 instrument、side、quantity、fill price、aware executed_at、
fee、tax、slippage 和组合 policy version。

## 12. Fee Policy

`ConfigurableFeePolicy` 注入 commission rate、minimum commission 和 sell stamp tax；
A 股费率未硬编码进 Domain。

## 13. Slippage Policy

`FixedBpsSlippagePolicy` 支持零滑点和固定 bps，BUY 向上、SELL 向下，无随机行为，
并单独记录价格影响成本。

## 14. Decimal / Currency

所有 financial arithmetic 使用 Decimal。没有 float 金额转换、隐式 FX 或 silent rounding。

## 15. Realized PnL

V1 weighted-average 公式：`(sell fill - average cost) × sold quantity - fee - tax`。
BUY 成本基数已包含交易费用；partial sell 测试验证剩余成本和贡献累计。

## 16. Unrealized PnL

`market value - quantity × average cost`，mark 必须由当前 replay timestamp 的 PIT Service 返回。

## 17. NAV

每个 snapshot 满足 `NAV = Cash + Σ Position Market Value`；result 满足
`Net Result = Final NAV - Initial Capital` 和对应 total return。

## 18. Portfolio Snapshot

Snapshot immutable，包含 portfolio、aware as_of、cash、排序后的 position summaries、market
value、realized/unrealized PnL 和 NAV。

## 19. NAV Series

Replay 对 PIT-visible OPEN sessions 每日生成一个确定性 NAV snapshot；不实现分钟或实时 NAV。

## 20. Benchmark

最小 benchmark foundation 保存 canonical instrument、首末 PIT mark、benchmark return 和
excess return。数据不足时明确 warning，不借用未来值。

## 21. PIT Data Access

唯一入口为 `PointInTimeMarketDataService + HISTORICAL_RESEARCH + aware as_of + RAW`。
Calendar、trade、mark、benchmark 均经该 façade；Application 不引用 canonical/historical repository。

## 22. No-Lookahead Evidence

`test_future_bar_is_never_borrowed_for_trade_or_mark` 在数据集中保留 future bar，但其
`available_at > as_of` 时 replay 返回 `PIT_DATA_UNAVAILABLE`，不会读取 latest/next bar。

## 23. Deterministic Replay

三 instrument、四 fills 的固定 500k 场景执行两次，完整 `BacktestRecord` 相等，稳定 event IDs
序列相等。stable IDs 基于固定 business inputs 的 SHA-256，不使用 UUID/random/wall clock。

## 24. Invalid Order Handling

覆盖 zero/negative quantity、invalid limit price、illegal lifecycle、buy exceeds cash、sell exceeds
position、wrong portfolio fill。失败不产生负现金或裸空头。

## 25. Insufficient Data Handling

空 calendar、缺失 price、future/not-yet-available price 均为 structured error；benchmark 缺失为
显式 warning 和零 baseline，不替换成 latest/下一根 bar。

## 26. Audit Ledger

稳定有序链：Run Created → Initial Capital → Order → Fill → Cash Change → Position Change →
NAV Snapshot。Audit payload defensive-copy 为 immutable mapping。

## 27. Persistence

Application-owned `BacktestRepository` 接收完整 evidence。PostgreSQL adapter 写入 runs、orders、
fills、cash ledger、NAV snapshots、audit events；run ID 使用 insert-or-verify，冲突不覆盖。

## 28. Migration

新增 `20260820_0008`，未修改旧 migration。已验证 previous head `20260817_0007` → 0008、
0008 → 0007 → head，以及全新数据库 upgrade head。

## 29. PostgreSQL Evidence

PostgreSQL 17-alpine 隔离容器运行真实 asyncpg/SQLAlchemy。测试验证六表各一条规范化证据、
重复 save 不增行、result read-back、identity conflict 与损坏数据 serialization failure。

## 30. Deterministic E2E

Initial CNY 500,000；A/B/C Day1 BUY；A Day3 SELL；每交易日对全部持仓 PIT mark；同时持有
三 instrument；验证 cash、average cost、PnL、NAV、benchmark、costs 和完整 replay equality。

## 31. Cost Transparency

Result 分列 gross result、fee、tax、slippage、net result；满足
`gross - net = fee + tax + slippage`。盈利判断应使用 Net。

## 32. Architecture Tests

25 passed。新增规则证明 Domain 无 Application/Infrastructure/SQL，Backtest Application 无
Tushare/HTTP/SQL/UI，必须引用 PIT Service，且无 direct historical/latest、Strategy、AI、Shadow、
leverage implementation；Fee/Slippage 通过 protocols 可替换。

## 33. Master Requirement Traceability

| Requirement | SPEC-005 Status | Evidence / Reason |
|---|---|---|
| Champion 500k compatibility | Foundation / Partial | 固定 500k E2E；资本可配置 |
| Multiple positions | Implemented | 同时持有 A/B/C |
| Continuous compounding compatibility | Foundation | current NAV 独立于 initial capital |
| Multi-asset | Future compatible | 复用 canonical InstrumentIdentity |
| Multi-horizon | Deferred | 未进入本规格 |
| Shadow Portfolios | Deferred | 明确非范围 |
| Leverage | Explicitly not implemented | no-negative-cash tests |
| Memory | Audit-compatible foundation | stable events/snapshots/source IDs |
| Governance | Audit-compatible foundation | stable policy versions/evidence |
| Committee Meetings | Deferred | 明确非范围 |
| Learning Lab | Deferred | 明确非范围 |

## 34. Full Test Evidence

隔离 PostgreSQL 17：`475 passed in 42.63s`。无 skip/xfail。包含 Domain、Accounting、
Order/Fill、Policies、Application、Architecture、PostgreSQL、Migration、PIT 和 deterministic E2E。

## 35. Coverage

- Repository total: 96.95%
- Backtest Application: 99%
- Portfolio Accounting: 96%
- Portfolio Models: 96%
- Fee/Slippage Policies: 100%
- PostgreSQL additions: 97%

全部达到规格分层 ≥95% 目标，总仓库高于 90% gate。

## 36. Ruff

`python -m ruff check .`：PASSED。

## 37. Mypy

Mypy strict：PASSED，101 source files。

## 38. WPF

Release build：PASSED，0 warnings / 0 errors。未修改 WPF。

## 39. Git Diff Check

`git diff --check`：PASSED。敏感文件模式扫描未发现 `.env`、keys、certificates 或 logs。

## 40. GitHub Actions

本文件与实现形成同一最终 commit 后 Push。必须等待该 exact SHA 的 Governance baseline、
Backend tests 和 Desktop build 全部 PASSED；结果采用 PR timeline + Actions run + Codex final
response 作为 external immutable attestation，不再创建 evidence-only commit。

## 41. Known Limitations

日线 close full-fill、long-only、CNY-only、单一 benchmark、RAW PIT prices；无 partial fill、T+1
lot、复杂 corporate-action accounting、FX、分钟/实时、Risk/Strategy/Broker/UI。

## 42. Technical Debt

- S005-D01：PIT-adjusted series 尚未实现，V1 仅 RAW。
- S005-D02：partial fill 与 T+1 sellable lots deferred。
- S005-D03：benchmark 缺失目前以 warning/zero baseline 表达。
- S005-D04：PostgreSQL V1 read port 只回读 structured result，完整 replay evidence 由规范化表审计。

以上均为显式非范围或可控限制，不破坏会计正确性、PIT 安全或 deterministic replay。

## 43. Final HEAD Attestation Requirement

完成 Push/Draft PR 后必须证明：Local HEAD = Remote branch HEAD = PR Head；exact SHA required CI
全绿；Workspace Clean。PR 保持 Draft，不 Merge，不开始后续 Phase。

## 44. Final Recommendation

```text
B. APPROVED CANDIDATE WITH NON-BLOCKING DEBT
```

最终 APPROVED 由 Architecture Review 决定。
