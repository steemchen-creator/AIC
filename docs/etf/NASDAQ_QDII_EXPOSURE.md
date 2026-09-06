# 纳斯达克 QDII 暴露语义

SPEC-009 的“纳指暴露”仅表示持有在中国交易所上市、以 CNY 交易的 QDII ETF，且其
`ETFTracksIndex` 指向纳斯达克指数参考身份。它不是直接持有美国股票或美国 ETF。

一个去品牌 fixture 具有以下明确事实：

```text
instrument_type: ETF
listing_venue: SSE
trading_currency: CNY
channel: QDII
underlying_market: US
underlying_currency: USD
exposure_family: NASDAQ
exposure_category: NASDAQ_100
benchmark: REFERENCE.INDEX:NDXFIX-GI
```

这些分类只来自显式映射证据，不从产品名称推测。缺失证据时保留 `UNKNOWN`。

## 可用时间

QDII 的净值、份额和部分源数据可能晚于境内收盘公布。PIT 查询只使用 `available_at <= as_of`
的事实；未来数据返回不可用，缺少可用时间返回 Unknown。系统不会因为交易日期较早就认为
数据当时已经可见，也不会从数据库读取“最新完整数据”补齐历史决策。

## 未实现

V1 不包含直接 Nasdaq/US execution、QQQ/QQQM、USD Cash、FX、美国交易日历、跨币种 NAV
或隐式汇率换算。未来如实现这些能力，必须增加独立市场日历、账户币种、FX/PIT 和执行规则，
不能复用本文件中的境内 QDII 执行语义作为 fallback。
