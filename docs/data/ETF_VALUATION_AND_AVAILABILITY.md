# ETF 估值与可用时间

`ETFValuationSnapshot` 保存交易日、NAV、收盘价、份额规模、溢折价、来源和可用时间。
字段允许缺失，缺失不会被填为零，也不会被解释为“无溢价”。

## 单位

Tushare Adapter 的规范化规则为：

- `fund_daily` 价格：CNY；
- `vol`：手，规范化后乘 100 成为份；
- `amount`：千元，规范化后乘 1000 成为 CNY；
- `etf_share_size.total_share`：万份，规范化后乘 10000 成为份；
- adjustment factor 保持精确 `Decimal`。

溢折价仅在 NAV 和 close 同时存在时计算：

```text
premium_discount_pct = (close - nav) / nav * 100
```

正值为溢价，负值为折价。结果只作为可审计数据基础，不在本阶段产生交易信号。

## PIT / No-Lookahead

估值、ETF profile、指数关系、指数参考和执行 profile 均通过明确的 `available_at` 进入
PIT 策略。DailyBar 在 Historical Research 中使用 Provider timestamp，在 Operational Replay
中使用 ingested timestamp。未来证据会被排除，未知证据保持 Unknown。

## Coverage

ETF Master、DailyBar、Valuation、Adjustment Factor 和 Index Reference 复用已有
`InstrumentCoverageAttempt` / `BackfillAttempt` 审计模型。`COMPLETED + received_count=0`
表示已执行请求且结果为空；没有 attempt 才表示尚未同步。两者禁止混同。
