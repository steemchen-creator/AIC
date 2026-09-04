# A 股确定性执行基础

SPEC-006 在 SPEC-005 的组合会计之上增加现金账户交易门禁。它不生成选股信号，
也不连接真实券商；它只把一个明确的 `ExecutionOrderIntent` 转换为可审计的
`FILLED` 或 `REJECTED` 结果。

## 执行顺序

```text
Order Intent
-> PIT Trading Calendar
-> PIT Instrument Lifecycle / Trading Status
-> Lot / Price Limit
-> Cash / Position / T+1
-> Pre-Trade Risk
-> ACCEPTED / REJECTED
-> Deterministic Fill
-> Accounting / Settlement / Risk Snapshot / Audit
```

`AShareExecutionService` 只通过 `PointInTimeMarketDataService` 获取当时可见的
交易日、证券生命周期、交易状态和 RAW 日线。它不访问 `latest` 数据，也不直接
依赖任何 Repository、Tushare 或 SQL 实现。缺少必要 PIT 价格、未知交易状态、
未知涨跌停边界均保守拒绝。

## A 股规则

- 只有 Calendar 明确为 OPEN 才会推进执行和 T+1 结算。
- 未上市、已知退市、停牌或 UNKNOWN 状态均拒绝新买卖。
- 普通股票买入必须为 100 股的整数倍；零数卖出在 V1 允许整股卖出。
- 卖出零股的交易所细分限制尚未完整建模，这是已记录限制。
- `PriceLimitBand` 是带 `available_at` 的外部证据；高于上限或低于下限拒绝，
  边界未知或证据在未来才可见时拒绝。
- 不允许卖空、融资、隐式杠杆或负现金。

## 版本和审计

每个结果记录 execution、lot、price-limit、settlement 和 risk 五类策略版本。
RiskDecision、RiskSnapshot、SettlementRolloverEvent 与审计事件均使用稳定业务身份。
审计时间线包含 Order Intent、Eligibility、Risk Decision、接受/拒绝、Fill、Cash、
Settlement Position、Risk Snapshot 和 NAV。

未来做 T、Kelly、动态杠杆、策略引擎、实盘和 UI 不属于本阶段。
