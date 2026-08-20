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
