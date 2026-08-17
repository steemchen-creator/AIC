# A股交易日历与交易时段

## 权威来源与边界

Market Calendar 是 AIC 市场时间事实的唯一来源。V1 通过 Provider Runtime 调用
Tushare `trade_cal`，持久化 SSE（`CN.SSE`）和 SZSE（`CN.SZSE`）每天的 OPEN/CLOSED
事实；Application 不依赖供应商字段或 HTTP。不存在记录与“已确认 CLOSED”不同，只有
成功的 coverage 区间才能证明日历完整。

## 时区与 Session

市场时区为 `Asia/Shanghai`，持久化的 session 时间转换为 UTC 且始终带时区。Tushare
V1 只提供交易日事实；常规时段由独立 A-share Session Policy 提供：09:30–11:30、
13:00–15:00，中午不是连续交易。Session 不等于集合竞价或撮合规则，本阶段不实现
撮合。Canonical Fact 允许未来以特殊时段替换默认 policy，但 V1 不虚构 Provider 字段。

## 查询、同步与历史缺口

Calendar Repository 支持精确日期、inclusive range、上一/下一交易日和有序交易日集合。
显式 Backfill 按可配置区间顺序调用 Runtime，OPEN 与 CLOSED 都使用 insert-or-verify，
不 silent overwrite。Historical DailyBar 仅在 Calendar coverage 完整时计算：OPEN 日期减去
已有 bar 日期，结果称为“候选缺口”。周末和已确认节假日不会成为缺口。

交易所 OPEN 不保证个股有 bar；停牌与数据缺失仍需未来 Instrument Trading Status 区分。
本阶段没有复权、特殊休市穷举、Redis、调度器、回测、模拟交易或真实交易。未来这些模块
必须复用同一 Calendar Service，不得各自使用 `weekday < 5` 或私有节假日表。
# Instrument-level distinction

Calendar answers whether an exchange is open. It does not prove that an individual
security should trade; Phase 9 Instrument Master and Trading Status provide that layer.
