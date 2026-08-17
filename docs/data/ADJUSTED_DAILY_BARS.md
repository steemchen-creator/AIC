# A 股复权 DailyBar

Canonical `DailyBar` 始终保存原始市场事实。Phase 10 的 `AdjustedDailyBar` 是派生投影，
身份由原始 `record_id`、复权模式和 `a-share-adjustment/v1` 共同确定，不建立第二套
持久化行情事实。

模式及公式（`F_d` 为当日官方因子，`F_end` 为请求区间最后一根 Bar 的因子）：

- `RAW`：价格乘数为 1；
- `FORWARD_ADJUSTED`（前复权）：OHLC × `F_d / F_end`；
- `BACKWARD_ADJUSTED`（后复权）：OHLC × `F_d`。

V1 只调整 OHLC。Volume 和 Turnover 保留原始市场值，原始 Bar 不修改。每一根请求 Bar
必须存在正数 Decimal 因子；缺失时抛出 `AdjustmentCoverageIncomplete`，绝不以 RAW
冒充复权结果。所有计算使用同一官方因子源和固定策略版本，可确定性重放。

未来研究、回测和技术指标必须显式记录所用模式；公司行动解释数据不在 V1 中反推因子。

普通全历史复权视图不等于 PIT 安全视图。Phase 11 的 PIT V1 只允许 RAW；前复权依赖
区间末端因子，前/后复权请求会显式抛出 Unsupported，而不会使用 `as_of` 之后的因子。
