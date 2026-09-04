# ADR-0004: Forward Paper Trading 与 Champion Portfolio 基线

- 状态：Accepted
- 日期：2026-09-04
- 规格：SPEC-007

## 原因

AIC 已有历史回测和 A 股执行/风控基础，但缺少严格按现实时间前进、可暂停恢复并持续记账的模拟
交易边界。若复用历史回测模式或直接读取最新数据库数据，会破坏 no-lookahead 约束和审计可信度。

## 决策

新增独立 `domain.paper`、`application.paper` 和 Application-owned persistence port。Forward Paper
固定使用 `OPERATIONAL_REPLAY`、显式 Clock、PIT Market Data、下一交易日开盘执行和收盘盯市。
官方 Champion 账户由 Application Factory 创建，持久化采用单事务恢复投影与规范化不可变证据。

## 影响

- SPEC-005 历史回测行为保持不变；
- SPEC-006 Execution Service 增加向后兼容的可配置 PIT 模式、参考价格字段和故障检查点；
- PostgreSQL 新增 Paper Account、Session、Intent、Performance、Trade Episode 和状态事件表；
- 后续决策源可以通过端口接入，无需修改 Paper Runtime 核心规则。

## 风险与控制

- 日线无法表达盘中成交不确定性：V1 固定 NEXT_OPEN，非法时序直接拒绝；
- 数据迟到或缺失可能阻止收盘：安全暂停且不得伪造 NAV；
- 崩溃可能发生在多阶段处理之间：原子保存、稳定身份和四个故障点恢复测试；
- 未来功能误用历史最新数据：架构测试禁止 Paper Application 直接依赖 Repository/Provider，并固定
  `OPERATIONAL_REPLAY`。

## 回滚

代码可按 PR 回滚。迁移 `20260904_0010` 可降级到 `20260903_0009`，但会删除 SPEC-007 Paper
Trading 表；任何非测试环境执行前必须备份并获得明确授权。
