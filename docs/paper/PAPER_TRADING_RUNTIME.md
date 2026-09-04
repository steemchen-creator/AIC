# Forward Paper Trading Runtime

## 定位与边界

SPEC-007 建立面向未来日期推进的模拟交易运行时。它与 SPEC-005 的历史研究回放严格隔离：

- 历史回测使用 `HISTORICAL_RESEARCH`；
- Forward Paper Trading 固定使用 `OPERATIONAL_REPLAY`；
- 行情、交易日历、标的状态和公司行动只经 `PointInTimeMarketDataService` 获取；
- Application 层依赖端口，PostgreSQL 实现在 Infrastructure 层；
- 决策由 `PaperDecisionSource` 输入，运行时不包含策略、AI 或选股逻辑。

任何必需证据处于 Unknown、不可用或尚未可用状态时，运行时不得回退到数据库“最新完整数据”。

## 账户生命周期

```text
CREATED -> READY -> RUNNING <-> PAUSED -> STOPPED -> CLOSED
                         \-> ERROR
```

账户必须通过显式 `ActivatePaperAccount` 命令和 Readiness Gate 才能进入运行状态。
暂停、恢复、停止均产生稳定、可审计的状态事件。已停止或关闭账户不能处理交易日 Session。

## 交易日 Session

```text
PLANNED -> OPEN -> PROCESSING -> MARKING -> FINALIZED
                 \-> BLOCKED -> PROCESSING
                 \-> FAILED
```

交易日由 PIT 可见的 SSE/SZSE Calendar 证据决定，而不是简单的自然日加一。休市日不创建
Session。每个账户和交易日只有一个确定性 Session 身份；已 Finalized 的 Session 不可重写。

## V1 执行时序

- 日线频率；
- 委托意图必须在目标交易日上午开盘前已存在；
- 成交参考价为目标 Session 的 PIT 可见开盘价；
- 同日收盘后才完整形成的 DailyBar 不能反向用于同日开盘成交；
- 盘前风险、T+1、整手、价格限制、现金和集中度规则复用 SPEC-006；
- 收盘净值使用当日 PIT 可见收盘价进行最终盯市。

运行时不会猜测部分成交或成交顺序，不会回补一个不确定的成交结果。

## 幂等、恢复与安全暂停

PostgreSQL 以账户恢复投影配合规范化证据表进行单事务保存。Session、Intent、Performance、
Trade Episode 和状态事件采用稳定身份；同内容重复写入幂等，身份相同但内容不同则拒绝。

以下故障点具有确定性恢复测试：

1. 风险判断后、成交前；
2. 成交后、记账前；
3. 记账后、快照前；
4. 快照后、Session Finalization 前。

缺少持仓收盘价或遇到 V1 不支持的公司行动时，账户进入 `PAUSED`，Session 进入
`BLOCKED`，并保留原因事件；不得伪造 NAV。证据恢复且 Readiness Gate 通过后，可显式恢复并
重新处理同一未完成 Session。

## 审计链

账户与 Session 事件记录稳定 ID、UTC 时间、来源、前后状态、运行状态及原因。每笔委托继续
保留 SPEC-006 的 `ORDER_INTENT -> ELIGIBILITY -> RISK_DECISION -> FILL -> CASH_CHANGE ->
POSITION_SETTLEMENT -> RISK_SNAPSHOT -> NAV` 审计链。

## 明确非范围

V1 不实现实盘交易、Broker 接入、撮合队列、部分成交、融券、融资、杠杆、外部出入金、策略
引擎、AI、大吉大利展示、影子组合、雷达或 UI。
