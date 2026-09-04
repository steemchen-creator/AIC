# REVIEW-SPEC006

## 1. Executive Summary

SPEC-006 已建立确定性 A 股现金账户执行与盘前风险底座。实现能够基于严格 PIT 证据
拒绝闭市、未上市、退市、停牌、状态未知、价格边界未知、数量非法、T+1 不可卖及
基础组合风险违规订单；允许的订单继续复用 SPEC-005 会计、费用和滑点模型。

## 2. Git / Branch / PR

- Base：`main`
- Feature：`feature/a-share-execution-risk`
- Draft PR：提交并 Push 后创建，标题为
  `feat(execution): add A-share trading and risk foundation`
- 本报告不授权 Merge。

## 3. Scope Confirmation

实现严格限定在 Session/Instrument eligibility、T+1、Lot、Price Limit、Pre-Trade
Risk、Risk Evidence、Persistence、Migration、Tests 和 Documentation。未实现 AI、
Strategy Engine、Shadow、Kelly、动态杠杆、实盘、券商、分钟/Tick、VaR 或 UI。

## 4. Architecture Diff

```text
domain/execution          immutable models + pure policies + SettlementBook
application/execution    PIT-only orchestration
application/ports        execution evidence contract
infrastructure           PostgreSQL insert-or-verify adapter
migrations/0009          execution/risk evidence schema
```

依赖方向保持 Application/Domain 不感知 PostgreSQL、Tushare、FastAPI 或 WPF。

## 5. A-Share Execution Model

`ExecutionOrderIntent` 进入 `AShareExecutionService`，结果为包含 terminal Order、
RiskDecision、可选 Fill、Cash、Settlement、RiskSnapshot、策略版本和 AuditEvent 的
不可变 `ExecutionOutcome`。

## 6. Session Eligibility

每次执行都调用 `PointInTimeMarketDataService.list_calendar_as_of()` 查询同一日期。
仅明确 OPEN 的 Calendar fact 允许继续；CLOSED 返回 `MARKET_CLOSED`，缺失返回
`PIT_DATA_UNAVAILABLE`。

## 7. Instrument Tradability

通过 `list_instruments_as_of()` 与 `list_trading_status_as_of()` 组合判断 listed、
delisted、TRADING、SUSPENDED、UNKNOWN。未知状态默认拒绝。

## 8. T+1 Model

`SettlementBook` 独立保存 total、sellable、today-bought，避免把交易所结算规则散落
进 SPEC-005 Portfolio Domain。

## 9. Sellable Quantity

BUY 当天只增加 total/today-bought；SELL 比较 requested 与 sellable。超过 total 同时
记录 `INSUFFICIENT_POSITION`，超过 sellable 记录
`INSUFFICIENT_SELLABLE_POSITION`。

## 10. Trading-day Rollover

Application 仅在 PIT Calendar 明确 OPEN 后调用 rollover；不使用 calendar date + 1，
周末和连续闭市日不会释放 today-bought。

## 11. Board Lot Policy

`AShareBoardLotPolicy` V1 要求 BUY 为正整数且 100 股整数倍。SELL 允许正整数股；
交易所零股必须一次性卖出等细则为非阻塞限制并已文档化。

## 12. Price Limit Policy

`ExplicitPriceLimitPolicy` 输出 UPPER/LOWER/WITHIN/UNKNOWN。`PriceLimitBand` 带来源和
`available_at`；未来才可见或缺失的 band 按 UNKNOWN 保守拒绝。

## 13. Suspension Handling

OPEN exchange day 上若 instrument 状态为 SUSPENDED，BUY 和 SELL 都拒绝，已有持仓
保持不变。

## 14. Order Acceptance Flow

执行顺序为 Calendar → Lifecycle/Status → Lot/Price → Position/T+1 → Risk →
ACCEPTED → deterministic Fill。任一失败产生 REJECTED Order、无 Fill、无会计变更。

## 15. Pre-Trade Risk Policy

`PreTradeRiskInput` 显式携带 PIT snapshot、instrument、side/quantity/price、
TradingEligibility、aware `as_of`、成本、sellable 和日内计数。Policy 无 I/O。

## 16. Risk Decision

每次判断生成不可变 `RiskDecision`；ID 由订单业务输入、决定、排序后的原因码和策略版本
确定性生成。ALLOW 不带原因，REJECT 至少带一个原因。

## 17. Risk Reason Codes

覆盖规格列出的全部原因，并增加 `PIT_DATA_UNAVAILABLE`，明确区分证据不可用与规则
不支持。

## 18. Single-position Limit

基于 post-trade position exposure / post-trade NAV；比例由配置注入。测试证明 20%
上限会拒绝形成 25% 暴露的订单。

## 19. Gross Exposure Limit

基于 post-trade gross exposure / post-trade NAV；配置构造时强制 `0 < limit <= 1`，
不能借该参数伪造简易杠杆。

## 20. Cash Buffer

支持 percentage 与 absolute amount，两者取更严格值。BUY 后现金低于缓冲即拒绝。

## 21. Trade Frequency Guard

支持 max orders/day、max filled orders/day 和 max daily turnover pct，均由 fixture/config
显式提供，不硬编码投资参数。

## 22. Risk/Execution Policy Versioning

每个结果记录 execution、lot、price-limit、settlement、risk 五类版本；历史证据不由
当前策略重新解释。

## 23. Risk Snapshot

每次 Fill 后生成稳定 RiskSnapshot，包含 NAV、cash、gross exposure、cash pct、largest
position pct、position count、turnover、orders 和 fills。

## 24. No Margin

RiskPolicyConfig 不允许 gross limit 超过 1.0；买入若导致现金不足或缓冲违规即拒绝。

## 25. No Short Selling

SELL 同时受 total 与 sellable quantity 约束；拒绝订单不生成 Fill，不可能形成负持仓。

## 26. Leverage Future Compatibility

接口保留可版本化风险策略，但 V1 只接受 1.0x 以内现金账户。Permission 不代表义务；
动态杠杆未实现。

## 27. Kelly Future Compatibility

Risk Gate 接收数量而不生成数量；未来 Kelly/Position Sizing 可提供 intent，再由本门禁
限制。当前没有伪实现 Kelly。

## 28. Predator Future Compatibility

系统允许没有订单的 session；执行层不要求每日交易，也不实现 Opportunity Scoring。

## 29. Audit Timeline

实际事件链为 ORDER_INTENT → ELIGIBILITY → RISK_DECISION → ORDER_ACCEPTED/REJECTED →
FILL → CASH_CHANGE → POSITION_SETTLEMENT → RISK_SNAPSHOT → NAV。

## 30. Persistence

Application-owned `ExecutionEvidenceRepository` 定义保存与读取 RiskDecision。PostgreSQL
适配器在单事务内 insert-or-verify，不静默覆盖；另提供确定性 InMemory 适配器。

## 31. Migration

新增 `20260903_0009_a_share_execution_risk.py`，不修改历史迁移。已验证 base→head、
0008→0009、0009→0008→head。

## 32. PostgreSQL Evidence

持久化表：`risk_decisions`、`execution_risk_snapshots`、`settlement_rollovers`、
`settlement_position_evidence`、`execution_audit_events`。冲突身份返回
`PERSISTENCE_IDENTITY_CONFLICT`。

## 33. T+1 E2E

CNY 500,000 场景覆盖 Day 1 BUY A/B、当日 SELL A 拒绝、下一 OPEN session SELL A
部分仓位成功、BUY C、非法 Lot 和停牌拒绝；核对现金、持仓、sellable、费用税、NAV、
决策、快照及审计。

## 34. Weekend/Holiday Evidence

测试明确覆盖 Friday BUY → Saturday/Sunday 不释放 → Monday OPEN 释放；另覆盖两个连续
closed-calendar gap 后才在 Thursday OPEN 释放。

## 35. Price Limit Evidence

测试覆盖 within → ALLOW、above upper/below lower → REJECT、missing/future band →
UNKNOWN_LIMIT 保守拒绝。

## 36. Suspension Evidence

测试覆盖停牌证券 BUY/SELL 均拒绝，且原持仓数量不变。

## 37. Concentration Evidence

fixture 配置 `max_single_position_pct=0.20`，125,000 / 500,000 的 post-trade 暴露被
`SINGLE_POSITION_LIMIT` 拒绝。

## 38. Gross Exposure Evidence

fixture 配置 10% gross 上限，形成 12% post-trade gross 的订单被拒绝。

## 39. Cash Buffer Evidence

fixture 配置 90% minimum cash buffer，买入后现金不足 90% NAV 的订单被拒绝。

## 40. Trade Frequency Evidence

max order、max fill 和 max turnover 三类 guard 均有独立确定性测试。

## 41. PIT / No-Lookahead

future Trading Status、future DailyBar、future PriceLimitBand 均不会被借用；当前持仓缺少
当日 PIT mark 时拒绝，不查询 latest。所有 context 使用 HISTORICAL_RESEARCH、aware
`as_of` 与 RAW adjustment。

## 42. Replay Determinism

同一完整场景执行两次，ExecutionOutcome、RiskDecision ID/reasons、accepted/rejected、
Fill、sellable、RiskSnapshot、NAV 和 audit chain 全部相等。

## 43. Architecture Tests

自动化测试证明 Domain/Application 不依赖外层；Execution 不 import Tushare/SQL/UI；
只通过 PIT Service 使用 Calendar/Lifecycle/Status；源码不含 latest、AI/LLM、Strategy、
Kelly、Shadow、Opportunity Radar、margin 或 dynamic leverage 实现。

## 44. Master Requirement Traceability

| Requirement | SPEC-006 Status |
|---|---|
| Champion 500k compatibility | Foundation |
| Multiple positions | Existing / Verified |
| T+1 | Implemented foundation |
| 做T compatibility | Foundation |
| Multi-horizon | Deferred |
| Multi-asset | Future compatible |
| Continuous compounding | Existing compatibility |
| Leverage Permission | Deferred / no-hidden-leverage enforced |
| Permission != Obligation | Future-compatible |
| Capital Allocation Brain | Deferred |
| Kelly | Deferred |
| Predator Principle | Future-compatible |
| Shadow | Deferred |
| Memory | Audit-compatible |
| Governance | Audit-compatible |
| Opportunity Radar | Deferred |
| Alpha Tribunal | Deferred |
| CMRO | Deferred |

## 45. Full Tests

命令：`pytest --cov --cov-report=term-missing`

结果：`524 passed in 49.45s`，无 skip/xfail。

## 46. Coverage

- Repository total：97.20%
- new execution domain models：100%
- new policies：100%
- new settlement：100%
- new application orchestration：97%
- new PostgreSQL adapter：100%

## 47. Ruff

`ruff check apps/backend/src apps/backend/tests`：Passed。

## 48. Mypy

`mypy` strict：Passed，108 source files 无问题。

## 49. WPF

`dotnet build apps/desktop/AIC.Desktop.csproj --configuration Release`：Passed，
0 warning / 0 error。SPEC-006 不修改 Desktop。

## 50. Git Diff

提交前执行 `git diff --check`；只包含 SPEC-006 代码、测试、迁移与同步文档。

## 51. GitHub Actions

Draft PR 创建后以最终 PR Head 对应的 Governance baseline、Backend tests、Desktop build
为准。由于 Commit SHA 不能自引用写入其自身内容，exact run/SHA 在本轮最终 Attestation
中报告，不创建 evidence-only commit。

## 52. Known Limitations

- 未完整实现卖出零股必须一次性卖出的细分规则。
- Corporate Action 对持仓数量/成本的完整会计交互仍延期。
- PriceLimitBand 由调用方提供明确、带时间的证据；本阶段不实现全部板块/ST/新股规则源。
- 仅 deterministic daily replay；不含部分成交、流动性或盘口冲击。

## 53. Technical Debt

上述限制均为规格明确的非阻塞边界。后续扩展应新增版本化 Policy 或审计数量事件，
不得把规则硬编码回 Portfolio Domain，也不得绕过 PIT Service。

## 54. Final HEAD Attestation Requirement

完成 Commit/Push 后必须证明 Local HEAD = remote feature HEAD = Draft PR Head，并确认该
SHA 的 required GitHub Actions 全绿、Workspace Clean。本文件不通过追加证据提交制造
循环 SHA。

## 55. Final Recommendation

**B. APPROVED CANDIDATE WITH NON-BLOCKING DEBT**

理由：全部强制基础范围、测试和本地质量门已满足；已知债务仅限规格允许延期的零股细则、
完整 Corporate Action 数量会计和全部涨跌停规则数据源。最终 Architecture Approval 由
外部 Architecture Review 决定。
