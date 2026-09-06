# Shadow Portfolios 与公平实验基础

SPEC-008 建立内部基金经理实验平台。Champion 是官方考核组合；Shadow 是实验组合。Shadow 的表现
不能自动替换 Champion、获得更多资金或触发晋升，任何晋升必须由未来独立治理流程决定。

## 运行结构

```text
Experiment Manifest + Fairness Contract
                    |
        Group Trading Session
          /       |       \
  Champion     Shadow A   Shadow B ...
      |            |          |
 independent Paper Account / Portfolio / NAV / audit
                    |
       Performance Comparison Snapshot
```

一个有效实验恰好包含一个 Champion 和至少三个 Shadow。基线 E2E 使用 Champion、Atlas、Sage、
Aegis，每个账户以 500,000 CNY 启动并连续复利。成员共用同一 Paper Runtime 服务配置，但账户记录、
组合身份、现金、持仓、损益、NAV、Intent 和事件完全独立。

## Experiment Manifest 与 Fairness Contract

Manifest 固定：

- PIT 和交易日历策略版本；
- 执行、风险、费率、滑点策略版本；
- Benchmark；
- 初始资金和开始日期；
- Experiment/Comparison 策略版本；
- 资产类别、交易场所和币种兼容范围；
- 成员角色资料和 Decision Source assignment。

以上字段使用规范化 JSON 计算 SHA-256 Policy Bundle identity。Fairness Contract 绑定所有成员账户、
初始资金与该哈希。成员不得声明不同的公平环境。

V1 Decision Source 只允许 `SCRIPTED`、`MANUAL`、`FIXTURE`。这些值只描述 Intent 来源，不包含 AI、
LLM 或策略引擎。

## 故障隔离与活动状态

Group Session 按稳定成员顺序运行。某一 Decision Source 缺失、标识不匹配或账户运行失败时，该成员
结果记为 `FAILED`，角色活动记为 `ERROR`，其他成员继续处理。关闭市场统一返回 `SKIPPED`。相同
group/date 重放直接返回已保存结果，不重复生成证据。

角色活动只聚合真实状态：`IDLE`、`READY`、`PROCESSING`、`WAITING`、`PAUSED`、`ERROR`。本阶段
没有 UI，也不生成与实际运行无关的动画状态。

`RoleActivityView` 至少提供 `manager_id`、`display_name`、`avatar_reference`、
`paper_account_id`、当前状态、当前任务引用、最近 Group Session、最近输出以及最新事件时间。
这些值来自已持久化的 Group Session/Role Activity；没有活动证据时状态为 `IDLE`，不会伪造任务。
成功成员的最近输出指向 Performance Snapshot，等待或错误成员保留对应 Group Session 任务引用。

## 头像更新与审计

`UpdateRoleAvatarReference` 只更新角色的有效头像引用。初始头像仍属于不可变 Manifest；每次实际
变化追加 `RoleAvatarReferenceUpdated`，保存 manager/account、前后引用和 UTC 时间。相同引用重放
是幂等 no-op。引用不能为空、不能超过 512 字符，也不能包含控制字符。

当前资料由初始 Manifest 与追加事件投影，因此 manager、Portfolio、Account、Experiment membership
以及历史 NAV、Order、Fill、Decision 和 Track Record 均不改变。头像上传、裁剪、对象存储和 WPF
编辑 UI 不在 SPEC-008 范围内。

## 比较与 Leaderboard

每个 Comparison Snapshot 包含 NAV、Return、Drawdown、Sharpe、Sortino、Calmar、Benchmark、
Excess Return、Turnover、Costs、Exposure、Cash 和 Position Count。综合排名由收益、风险调整、回撤
和成本多个维度确定，并使用 account ID 稳定破同分。

样本状态为：

- `INSUFFICIENT_SAMPLE`：不足以形成结论；
- `PROVISIONAL`：可观察但不可正式定论；
- `QUALIFIED`：满足比较门槛。

没有 `QUALIFIED` 成员时，`qualified_winner_account_id` 必须为空。

Comparison Policy 版本通过不可变 Policy Bundle 绑定历史快照。调用方提供的成员顺序会在创建时按
Champion/Role Identity 规范化；正序与逆序运行产生相同的逐 Portfolio 订单、风控、成交、现金、
持仓、结算、NAV、绩效和业务审计证据。

## 多资产兼容边界

组合不按市场建立子类型。资产兼容性由 `Portfolio + Instrument + AssetClass + MarketVenue + Currency`
组合表达。模型已预留股票、ETF、现金、指数、期货，美国 Nasdaq/NYSE 与常用币种元数据。

SPEC-008 不实现海外日历、成交规则、换汇、保证金、做空或实时经纪商。现有 Forward Paper 运行仍为
A 股、CNY、long-only、无杠杆，并继续强制 `OPERATIONAL_REPLAY` 和 PIT no-lookahead。

## SPEC-009 ETF 集成

Experiment AssetUniverse 中的 ETF 现已成为真实可执行资产，而不再只是兼容枚举。自动化测试让
Atlas Shadow 通过同一 Manifest、PIT、Execution、Risk、Fee 与 Paper Runtime 买入并持有境内 ETF，
同时证明 Champion、Sage、Aegis 账户没有该持仓。ETF 产品 profile 差异属于 instrument fact，
不改变 Fairness Contract；Comparison 仍以各账户独立的 CNY NAV 和同一 Benchmark 计算。

持有纳指 QDII ETF 仅表示境内产品暴露，不表示 Shadow 已在美国市场执行。
