# Point-in-Time Market Data

PIT 查询回答“在 `as_of` 时 AIC 合法可见什么”，而不是“数据库现在保存什么”。市场
`event_time`、供应商可用时间、AIC `ingested_at/retrieved_at` 和研究 `as_of` 是不同概念。

`PointInTimeContext` 是不可变的 Application 输入，包含 aware `as_of`、availability mode、
adjustment mode 和固定策略版本 `point-in-time-availability/v1`。结构化结果包含记录、逐条
availability decision、future/unknown 计数和 warning。

- `HISTORICAL_RESEARCH`：仅使用持久化 `provider_timestamp` 证明历史可用性；缺失为 Unknown。
- `OPERATIONAL_REPLAY`：DailyBar 使用 `ingested_at`，其他事实使用 `retrieved_at`，严格重放 AIC 信息集。

同一条今天回填的 2020 DailyBar，在有 2020 provider timestamp 时可进入 Historical
Research；在 2020 Operational Replay 中仍不可见。Calendar 的 Historical Research V1
是显式 ex-ante policy，临时修订风险保留。普通 Historical Service 不具备 PIT 保证。

PIT instrument universe 复用 listing lifecycle；上市日前排除，退市只有在退市知识已可用
时排除，未知退市知识保守保留并给 warning。返回 canonical identity，不把当前名称冒充
历史名称。
