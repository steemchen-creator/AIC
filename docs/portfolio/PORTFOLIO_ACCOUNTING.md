# Portfolio Accounting

Portfolio is a multi-instrument, CNY, long-only accounting aggregate. Initial capital is
an input (CNY 500,000 is only the reference E2E case), while current NAV remains available
as a future session capital base.

## Position semantics

V1 uses weighted-average cost. A BUY increases quantity and folds notional plus fee/tax
into cost basis. A SELL reduces quantity and records:

```text
realized PnL = (fill price - average cost) × sold quantity - fee - tax
```

Slippage is represented separately for cost transparency; its price impact is already
present in the fill price. Zero quantity, negative quantity, invalid price, insufficient
cash and insufficient position are explicit errors. Cash cannot become negative and a
position cannot become a naked short.

## Valuation

Marks must be PIT-safe. Each immutable daily snapshot satisfies:

```text
market value = Σ(quantity × PIT mark)
unrealized PnL = Σ(market value - quantity × average cost)
NAV = cash + market value
total PnL = NAV - initial capital
```

See `CASH_AND_PNL.md` for cash-ledger and cost presentation rules.

## SPEC-009 混合资产

同一个 CNY Portfolio 可以同时持有 A 股 Equity 和 SSE/SZSE 上市 ETF，Position Key 保留完整
InstrumentType，因此同代码不同资产类型不会混淆。QDII ETF 仍以 CNY 成交、记账和计算 NAV；
底层 USD 只是暴露元数据，不触发 FX 或 USD Cash。不可交易 Index 只能作为 Benchmark，不能成为
Position。所有费用继续使用 Decimal，并由 asset-aware fee policy 按资产类型选择配置。
