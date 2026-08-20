# Cash, Costs and PnL

Cash is not an untraceable mutable balance. Every change creates an immutable entry with
stable identity, aware timestamp, source fill/run, signed amount and balance after entry.
V1 entry types are INITIAL_CAPITAL, BUY_SETTLEMENT, SELL_SETTLEMENT, FEE, TAX and
ADJUSTMENT. The implementation does not silently round Decimal financial values.

Backtest results expose:

- gross result;
- commission/fees;
- sell-side taxes;
- deterministic slippage cost;
- net result and total return;
- realized and unrealized PnL;
- benchmark and excess return.

Profitability decisions must use net result. Fee/tax rates live in injected policies,
not in Portfolio Domain, so A-share rules are explicit and versioned.
