# ETF 执行规则证据

ETF 的交易规则不是资产类别常量。`InstrumentExecutionProfile` 以产品和生效日为维度保存：

- CNY 交易币种；
- board lot；
- `T0`、`T1` 或 `UNKNOWN` 结算能力；
- 涨跌幅规则引用；
- 交易日历引用；
- 证据来源、可用时间和策略版本。

执行前必须通过 `ETFPointInTimeService.execution_profile_as_of()` 选择在决策时点已经可见、
且在交易日已经生效的版本。未来版本、缺失配置或 `UNKNOWN` 结算规则都会安全拒绝，
不会回退到通用 ETF 假设。

## 结算

- 明确 `T0`：当日买入数量可立即卖出；
- 明确 `T1`：当日买入不可卖，下一个确认开市日由现有 SettlementBook 释放；
- `UNKNOWN`：拒绝交易。

这一区分依赖产品规则证据。不能把所有境内 ETF 统一视作 T+0 或 T+1。

## 手数、涨跌幅与成本

board lot 从生效的产品 profile 读取。涨跌幅仍使用现有显式 PriceLimitBand；缺失或未来
Band 会安全拒绝。`ConfiguredAssetFeePolicy` 分别配置 Equity 与 ETF 的佣金和税费，
所有金额使用 `Decimal`，并把 fee、lot、settlement、risk 与 execution 版本写入执行证据。

指数没有执行 profile，也永远不是合法订单标的。`NON_TRADABLE_REFERENCE_INSTRUMENT`
会在市场数据读取前直接拒绝指数订单。
