# ETF 标的模型

SPEC-009 将境内上市 ETF 作为 AIC 第一个可执行的第二资产类别。ETF 使用
`InstrumentIdentity(market, symbol, ETF)`，市场只能是 SSE 或 SZSE；它和
`EQUITY`、不可交易的 `INDEX` 是不同类型。

## 主数据

`ETFInstrumentProfile` 保存展示名称、上市状态、产品通道、跟踪指数、管理人、管理费、
底层市场、底层币种、交易币种、暴露类别与暴露家族。所有来源事实携带
`DataProvenance` 和可用时间。未知分类保持 `UNKNOWN`，禁止根据名称猜测。

产品通道包括：

- `DOMESTIC`：境内产品；
- `QDII`：境内上市、通过 QDII 结构提供境外资产暴露；
- `UNKNOWN`：证据不足，不推断。

V1 的交易账户和估值账本仅支持 CNY。QDII ETF 的底层币种可以是 USD，但这不代表
系统已经实现 USD 现金账户、换汇或美国市场直接交易。

## 跟踪关系

`ETFTracksIndex` 显式连接 ETF 与 `IndexReference`。Provider 只提供源数据，
Normalizer 建立来源中立的规范化身份；Portfolio 只持有 ETF，不持有指数。
上游只提供当前关系而缺少历史生效区间时，`current_relationship_only=true` 会明确记录
这一限制，不能伪造历史关系。

## 数据入口

Tushare Adapter 支持 `etf_basic`，通过已有 Provider Runtime 调用。数据必须经过：

```text
Provider -> RawObservation -> ETF Normalizer -> Domain validation -> Repository
```

普通 CI 使用去品牌、确定性的 Tushare-like fixture，不访问实时网络。同步返回空集合会写入
coverage attempt；它表示该次请求确认返回 0 行，而不是自动证明 ETF 不存在。

## 明确边界

- 买大盘或行业暴露必须买可交易 ETF，不能下单买指数；
- 支持 A 股与境内 ETF 混合持仓；
- 不支持直接美股、QQQ/QQQM、USD 账户、FX、美国交易日历或跨币种 NAV；
- 不在本阶段实现 AI Brain、Opportunity Radar、Kelly、杠杆或 UI。
