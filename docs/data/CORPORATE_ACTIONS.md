# A 股公司行动

Phase 10 将公司行动保存为与供应商无关的 Canonical Fact。V1 从 Tushare `dividend`
接口中仅映射有明确字段证据的现金分红、送股和转增；配股、拆分、合并保留可扩展枚举，
但不会根据行情缺口猜测事实。

`record_date`、`ex_date`、`pay_date` 和 `effective_date` 分别保存，缺失值保持 `None`。
所有金额和比例使用 `Decimal`，所有事实携带 Provider、源记录、原始载荷哈希和转换版本。
重复事实返回 `ALREADY_EXISTS`，同一身份不同内容返回 `IDENTITY_CONFLICT`，不静默覆盖。

同步是显式操作，经 Provider Runtime → RawObservation → Tushare Normalizer → Repository；
普通历史查询不会触发网络调用。V1 不处理股东账户级现金、股份或配股结算，也不维护完整
修订历史。供应商后续修订将作为冲突显式暴露，等待独立 Revision Policy。

PIT 查询还要求公司行动的可用证据不晚于 `as_of`。Historical Research 使用
`provider_timestamp`，Operational Replay 使用 `retrieved_at`；缺失证据为 Unknown，
未来公告不会泄漏给过去的决策。
