# AIC Champion Paper Portfolio

## 官方账户基线

SPEC-007 只定义一个官方 Forward Paper 账户：

- 名称：`AIC Champion Paper Portfolio`；
- 初始资金：`500000 CNY`；
- 模式：`FORWARD_PAPER`；
- 资金模式：`CONTINUOUS_COMPOUNDING`；
- 执行策略版本：`next-session-open/v1`；
- Session 策略版本：`daily-bar-forward-paper/v1`。

固定名称和初始资金属于 Application 组合规则，不污染通用 Portfolio Domain。账户初始资金只在
创建时写入一次，后续盈亏连续进入 NAV，不按日重置，也不允许 V1 外部出入金。

## 决策输入

`PaperDecisionSource` 是唯一决策来源边界。测试使用确定性 Scripted Fixture；生产组合可以在后续
规格中提供新实现，但不得让 Paper Runtime 直接依赖 Strategy、AI、Provider 或数据库查询。

合法 Intent 必须包含稳定身份、账户、提交时间、目标交易日、标的、方向、数量和来源引用。
Intent 固定为 `NEXT_OPEN`，并必须在目标 Session 开盘前形成。

## 组合与会计连续性

账户支持多个 A 股多头持仓并复用 SPEC-005/006 的现金、成本、持仓、费用、税费、滑点和 T+1
结算模型。每个交易日从上一个 Finalized 状态继续，不重新创建初始组合。无交易日仍会在数据完整
时形成 Session 与净值快照，以保持连续净值序列。

## 风险控制

- 不允许负现金、裸卖空、隐含杠杆；
- Unknown PIT 证据按拒绝或阻塞处理；
- 缺少持仓盯市价时禁止 Finalize；
- 不支持的公司行动触发安全暂停；
- 账户和已 Finalized Session 的历史证据不可变。

## 未来激活仪式兼容性

V1 只提供可审计的显式 Activation Command 与状态事件，不实现“大吉大利”展示或 UI 仪式。
后续展示层可以订阅该命令结果和事件，无需改变账户生命周期或交易规则。

```text
“大吉大利” -> future UI authorization phrase -> ActivatePaperAccount
            -> readiness gates -> RUNNING
```

该短语永远不能绕过数据、PIT、Calendar、Execution、Risk、Database Health 或账户状态门禁。
