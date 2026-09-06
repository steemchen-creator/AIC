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

## 比较与 Leaderboard

每个 Comparison Snapshot 包含 NAV、Return、Drawdown、Sharpe、Sortino、Calmar、Benchmark、
Excess Return、Turnover、Costs、Exposure、Cash 和 Position Count。综合排名由收益、风险调整、回撤
和成本多个维度确定，并使用 account ID 稳定破同分。

样本状态为：

- `INSUFFICIENT_SAMPLE`：不足以形成结论；
- `PROVISIONAL`：可观察但不可正式定论；
- `QUALIFIED`：满足比较门槛。

没有 `QUALIFIED` 成员时，`qualified_winner_account_id` 必须为空。

## 多资产兼容边界

组合不按市场建立子类型。资产兼容性由 `Portfolio + Instrument + AssetClass + MarketVenue + Currency`
组合表达。模型已预留股票、ETF、现金、指数、期货，美国 Nasdaq/NYSE 与常用币种元数据。

SPEC-008 不实现海外日历、成交规则、换汇、保证金、做空或实时经纪商。现有 Forward Paper 运行仍为
A 股、CNY、long-only、无杠杆，并继续强制 `OPERATIONAL_REPLAY` 和 PIT no-lookahead。
