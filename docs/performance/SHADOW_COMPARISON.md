# Shadow Experiment Performance Comparison

比较层消费各独立 Paper Account 已完成的 `PaperPerformanceSnapshot`，不读取或修改组合内部状态。
同一 Group Session 的所有成员必须绑定相同 Policy Bundle Hash 和 PIT cutoff。

V1 保存以下维度：NAV、总收益、最大回撤、Sharpe、Sortino、Calmar、Benchmark 收益、超额收益、
换手、总成本、总敞口、现金与持仓数。总成本为 commission、tax、slippage 的显式合计。

排名分别计算收益、风险调整、回撤和成本名次，再形成稳定综合顺序。该顺序是对比基础，不是资金分配、
Champion 晋升或投资建议。只有 `QUALIFIED` 样本才可能产生 `qualified_winner_account_id`；短样本结果
始终为空。
