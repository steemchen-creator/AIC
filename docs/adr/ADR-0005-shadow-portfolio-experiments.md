# ADR-0005：Shadow Portfolio 公平实验与多资产兼容边界

- 状态：Accepted
- 日期：2026-09-06
- 规格：SPEC-008

## 原因

SPEC-007 只有一个官方 Champion 组合，无法在相同市场证据和执行规则下并行检验多个独立决策来源。
若为每个角色复制交易引擎，或让实验层直接改写组合账本，将造成规则漂移、状态串扰和不可审计的比较。
同时，直接建立 `AStockPortfolio` 会把组合身份永久绑定到当前 A 股实现，阻断未来 ETF、海外市场和
多币种扩展。

## 决策

新增 `domain.experiments`、`application.experiments`、Application-owned Port 和 PostgreSQL
Adapter。`ShadowExperimentService` 复用一个无账户内存状态的 `PaperTradingRuntime` 服务；每个
成员拥有独立 Paper Account、Portfolio、现金、持仓、PnL、NAV 和审计证据。

Experiment Manifest 保存 Champion、至少三个 Shadow、角色资料和明确的 Scripted、Manual 或
Fixture 决策源分配。Fairness Contract 绑定同一 PIT、日历、执行、风控、费率、滑点、基准、
初始资金和开始日期；Policy Bundle 采用规范化 SHA-256 身份，创建后不可变。

组合继续使用通用 `Portfolio`、`InstrumentIdentity` 和 `Money`。实验资产范围由 `AssetClass`、
`MarketVenue`、`Currency` 元数据描述；V1 只运行现有 A 股/CNY 执行路径，但模型可以表达 ETF、
美国市场和其他币种，不在本阶段实现海外交易规则或货币换算。

## 影响

- `PaperTradingRuntime.create_champion()` 保持原行为，并委托新增的通用账户创建入口；
- Group Session 以稳定顺序逐账户执行，一个成员失败不会停止其他成员；
- 比较快照同时保留收益、回撤、风险调整指标、Benchmark、超额收益、换手、成本、敞口、现金、
  持仓数和样本状态；
- 样本分为 `INSUFFICIENT_SAMPLE`、`PROVISIONAL`、`QUALIFIED`，未达标时不得产生正式优胜者；
- PostgreSQL 新增 Manifest、成员、组会话、比较快照和角色活动证据表。

## 风险与控制

- **公平规则漂移**：Manifest、Fairness Contract 与 Policy Hash 一并持久化；
- **组合状态串扰**：每个成员使用不同 account/portfolio identity，交易状态只存在各自 Paper Record；
- **故障扩散**：组编排捕获单成员异常，记录稳定错误码并继续；
- **短样本误判**：未到 `QUALIFIED` 不产生正式优胜者，Leaderboard 不只按收益排序；
- **伪造角色活动**：活动仅由实际创建、处理、等待或错误边界产生；
- **过早实现多资产交易**：海外市场、换汇和市场规则明确留在后续独立规格。

## 回滚

代码可按 PR 回滚。迁移 `20260906_0011` 可降级到 `20260904_0010`，但会删除全部 Shadow
实验元数据与比较证据；任何非隔离测试环境执行前必须备份并获得明确授权。Paper Account 表不受该
降级影响。
