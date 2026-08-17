# No-Lookahead Policy V1

所有未来 Research、Backtest、Signal 和 Paper Trading 必须经 PIT façade 并记录：
`decision_time`、`as_of`、availability mode、policy version 和 adjustment mode。

分类只有三种：

- `AVAILABLE`：有证据且 `available_at <= as_of`；
- `NOT_YET_AVAILABLE`：有证据但晚于 `as_of`；
- `UNKNOWN_AVAILABILITY`：没有足够证据；Unknown 不等于 Available。

公司行动、复权因子和停复牌状态都按此过滤，未来信息不会泄漏。历史行不会用
`event_time/created_at` 伪造 availability。Migration 0007 的 nullable provider timestamp
只保存真实 provenance，NULL 保持 Unknown。

Backtest-safe V1 价格默认且仅支持 RAW。PIT 前/后复权请求显式 Unsupported，因为普通
前复权会使用区间末端因子，可能包含 `as_of` 后信息。普通全历史复权仍可用于展示，但不
能冒充 PIT 数据。

V1 不实现完整 Instrument SCD、供应商 revision history、Calendar revision policy、策略、
Portfolio 或 Paper Trading。
