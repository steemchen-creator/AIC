# Paper Performance Baseline

## 每日快照

每个 Finalized 交易日保存一份不可变 Performance Snapshot，至少包含：

- Cash、Market Value、Realized/Unrealized PnL、NAV；
- Gross PnL、Net PnL、Gross Exposure；
- Cash Ratio、最大持仓占比、持仓数量；
- Benchmark Value、Daily/Cumulative/Benchmark/Excess Return；
- Peak NAV、Current/Maximum Drawdown；
- CAGR、年化波动率、Sharpe、Sortino、Calmar；
- Turnover、Commission、Tax、Slippage 和 Fill 数；
- 指标策略版本与样本充分性。

金额使用 `Decimal` 和 CNY，时间必须包含时区。`Net PnL = Gross PnL - Fee - Tax -
Slippage`，初始资金在整个账户生命周期保持不变。

## 计算约定

- Daily Return：本日 NAV 相对上一交易日 NAV；首日相对初始资金；
- Total Return：当前 NAV 相对初始资金；
- Drawdown：当前 NAV 相对历史 Peak NAV；
- Benchmark Return：当前基准值相对首个快照基准值；
- Excess Return：组合 Total Return 减 Benchmark Return；
- 年化基准：默认 252 个交易日；
- CAGR：默认至少跨越 365 个自然日才输出；
- 风险比率：默认至少 20 个收益样本才标记为 `SUFFICIENT`。

样本不足时不伪造年化指标，快照明确标记 `INSUFFICIENT_SAMPLE`。

## Trade Episode 与胜率

Trade Episode 按单一标的的完整持仓周期定义：持仓从 0 变为正数开始，到再次归零结束。中途
部分卖出不会提前形成 Episode。胜率、平均盈利、平均亏损、盈亏比、Profit Factor 和 Expectancy
只基于已关闭 Episode；开放持仓不计入胜率。

## 成本透明性

Performance Snapshot 分别保存手续费、印花税与滑点。指标不得把成本合并成不可解释的单一调整，
并可从 Fill 和现金账本追溯。
