# 指数参考身份

`IndexReference` 是来源中立、不可交易的参考数据。身份固定使用
`InstrumentIdentity(REFERENCE.INDEX, symbol, INDEX)`，避免把 `.GI` 等 Provider 命名空间
误认为交易所或可下单标的。

指数可以：

- 作为 Champion/Shadow/Backtest 的 Benchmark；
- 通过 `ETFTracksIndex` 描述 ETF 的跟踪目标；
- 保存指数 DailyBar，用于同日期、同口径的 tracking difference。

指数不能：

- 进入订单或 SettlementBook；
- 被当作持仓；
- 继承 ETF 的交易日历、手数、T0/T1 或费率。

`calculate_tracking_difference()` 使用精确 `Decimal` 计算 ETF 与 Benchmark 的同日期收盘收益
差，记录策略版本，不生成交易信号。指数同步空结果只表示本次 Provider 请求返回 0 行，
不能自动解释为指数不存在。
