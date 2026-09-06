# Shadow Experiment Performance Comparison

比较层消费各独立 Paper Account 已完成的 `PaperPerformanceSnapshot`，不读取或修改组合内部状态。
同一 Group Session 的所有成员必须绑定相同 Policy Bundle Hash 和 PIT cutoff。

V1 保存以下维度：NAV、总收益、最大回撤、Sharpe、Sortino、Calmar、Benchmark 收益、超额收益、
换手、总成本、总敞口、现金与持仓数。总成本为 commission、tax、slippage 的显式合计。

排名分别计算收益、风险调整、回撤和成本名次，再形成稳定综合顺序。该顺序是对比基础，不是资金分配、
Champion 晋升或投资建议。只有 `QUALIFIED` 样本才可能产生 `qualified_winner_account_id`；短样本结果
始终为空。

V1 `ComparisonPolicy.version` 为 `shadow-comparison/v1`，同时冻结在 Experiment Policy Bundle 中。
综合分依次合计 Return Rank、Risk-adjusted Rank、Drawdown Rank 和 Cost Rank；Risk-adjusted Rank
由 Sharpe、Sortino、Calmar 名次合计。所有同分最终按稳定 account ID 升序破序。

默认边界为少于 5 个 Session：`INSUFFICIENT_SAMPLE`；5 至 19 个：`PROVISIONAL`；20 个及以上：
`QUALIFIED`。只有综合排名第一且达到 `QUALIFIED` 才会写入快照的 qualified winner，但该结果不会
触发自动 Promotion。Policy 版本变化会形成不同 Policy Bundle identity；现有 Manifest 和历史比较
快照由 insert-or-verify/append-only 约束保护，不会被重写。
