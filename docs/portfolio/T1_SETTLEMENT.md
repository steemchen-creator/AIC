# A 股 T+1 结算基础

`SettlementBook` 与 SPEC-005 的会计持仓分离，专门跟踪：

```text
total_quantity
sellable_quantity
today_bought_quantity
```

当天 BUY 增加 total 和 today-bought，不增加 sellable；SELL 只能扣减 sellable。
因此普通股票当日买入后当日卖出会以 `INSUFFICIENT_SELLABLE_POSITION` 拒绝，
即使 total quantity 足够。

## 交易日推进

结算簿自身不猜测周末或节假日。Application 先通过 PIT Trading Calendar 确认 OPEN，
再调用确定性 rollover。下一个 OPEN session 才把 previous today-bought 释放为 sellable。
因此星期五买入不会在周六、周日释放；星期一 OPEN 才可卖。连续节假日同理。

这种分离保留未来做 T 的兼容性：已有可卖底仓可以日内先卖，而当日买回的数量仍进入
today-bought，不能再次卖出。

## 已知边界

- V1 允许卖出任意正整数股，尚未覆盖交易所关于零股必须一次性卖出的全部细节。
- Corporate Action 的完整数量调整不在 SPEC-006；后续可通过独立、可审计的数量事件
  扩展 SettlementBook，不能用 adjusted price 代替真实股数调整。
- 不支持卖空、融资融券或跨资产结算。
