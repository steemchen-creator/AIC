# 确定性盘前风险门禁

`PreTradeRiskPolicy` 是可替换、无 I/O 的风险门禁，不负责选股、预测或生成 Alpha。
所有参数来自显式 `RiskPolicyConfig`，每次判断生成不可变 `RiskDecision`，记录原因码、
输入摘要、`as_of` 和策略版本。

## 输入和计算

输入包含当前 PIT PortfolioSnapshot、Order Intent、证券、参考价、TradingEligibility、
T+1 可卖数量、交易成本、日内计数与明确时区的 `as_of`。

```text
notional = quantity * deterministic fill price
post position exposure = current position exposure +/- notional
post gross exposure = current gross exposure +/- notional
post cash = cash - buy notional / + sell notional - fees - taxes
post NAV = current NAV - fees - taxes
```

门禁可配置：

- `max_single_position_pct`
- `max_gross_exposure_pct`（强制不高于 1.0）
- `minimum_cash_buffer_pct` / `minimum_cash_amount`
- `max_orders_per_day`
- `max_filled_orders_per_day`
- `max_daily_turnover_pct`

RiskSnapshot 记录交易后的 NAV、现金、总暴露、现金比例、最大单一持仓比例、持仓数、
日换手和订单计数。不包含 VaR、ES、因子风险或相关性风险。

## 保守拒绝

原因码覆盖闭市、未上市、退市、停牌、状态未知、现金不足、持仓不足、可卖持仓不足、
数量非法、价格越界、涨跌停未知、集中度、总暴露、现金缓冲、交易频率、PIT 数据不可用
及不支持规则。ALLOW 不携带拒绝原因；REJECT 至少携带一个稳定原因码。

不同 Exploration/Validation/Predator 参数可在未来作为不同版本的配置注入，但本阶段
不实现模式引擎、Kelly、Opportunity Radar、动态杠杆或自动缩单。
