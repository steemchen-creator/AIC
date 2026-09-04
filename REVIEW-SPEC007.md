# REVIEW-SPEC007

## 1. Executive Summary

SPEC-007 已建立正式的 Forward-only Paper Trading Foundation：官方 500,000 CNY Champion
账户、连续复利、多持仓、PIT-safe 下一交易日开盘执行、收盘盯市、绩效基线、原子恢复和完整审计
证据。实现未加入策略、AI、实盘、Broker、杠杆或 UI。

候选结论：`B. APPROVED CANDIDATE WITH NON-BLOCKING DEBT`。

## 2. Git / Branch / PR

- Base：`main`，SPEC-006 closeout commit `88d9b4676d3aa6c6aef2345df73189bf4652f26a`；
- Branch：`feature/forward-paper-trading`；
- Implementation commit：`84f7df01555331478178f5c6b41ba005488ae7e0`；
- Draft PR：[PR #8](https://github.com/steemchen-creator/AIC/pull/8)；
- PR 保持 Draft，未 Merge，未开始 SPEC-008。

## 3. Scope Confirmation

范围仅包括 Paper Account/Session/Intent、Champion 账户、连续组合状态、PIT-safe 日线执行、绩效、
Trade Episode、审计事件、持久化、迁移、测试和文档。Explicit Non-Scope 均未实现。

## 4. Architecture Diff

- Domain：新增 `apps/backend/src/aic_backend/domain/paper/`；
- Application：新增 `application/paper.py` 与 `application/ports/paper.py`；
- Infrastructure：新增 `infrastructure/paper_persistence.py`；
- Existing Execution：仅增加向后兼容的 Availability Mode、开/收盘参考价、执行策略版本和故障
  checkpoint 注入；默认行为仍是 `HISTORICAL_RESEARCH + close`；
- Database：新增 migration `20260904_0010`；
- 决策原因、影响、风险和回滚见 `docs/adr/ADR-0004-forward-paper-trading.md`。

## 5. Research vs Forward Separation

`application/backtest.py` 保持 `HISTORICAL_RESEARCH`；`application/paper.py` 固定
`OPERATIONAL_REPLAY`。架构测试
`test_spec_007_paper_runtime_keeps_forward_pit_and_clean_architecture_boundaries` 自动验证隔离。

## 6. Paper Account Model

`PaperAccount` 是不可变 Domain Model，包含稳定 Account/Portfolio 身份、初始资金、模式、资金模式、
生命周期、时区时间和最后 Finalized 交易日，并校验正资金与单调前进。

## 7. Champion 500k

`PaperTradingRuntime.create_champion()` 在 Application 层固定创建
`AIC Champion Paper Portfolio`，初始资本为 `500000 CNY`。通用 Portfolio Domain 未硬编码
Champion 名称或金额。

## 8. Continuous Compounding

每个 Session 从持久化的 `PaperPortfolioState` 恢复现金、持仓、账本、结算和上次快照。初始资本只
创建一次；盈亏进入连续 NAV，不按日重置，无 V1 外部现金流。

## 9. Account Lifecycle

状态机位于 `domain/paper/models.py`：
`CREATED -> READY -> RUNNING <-> PAUSED -> STOPPED -> CLOSED`，并支持受控 `ERROR` 路径。
非法迁移抛出稳定的 `PaperErrorCode.INVALID_ACCOUNT_STATE`。

## 10. Session Lifecycle

`PLANNED -> OPEN -> PROCESSING -> MARKING -> FINALIZED`；数据/公司行动阻塞时进入 `BLOCKED`，
可恢复到 `PROCESSING`。Finalized/Failed 为终态。

## 11. Activation

`ActivatePaperAccount` 是显式 Application Command。`PaperReadinessGate` 在账户进入 RUNNING 前校验
数据、PIT、Calendar、Execution/Risk policy 和数据库健康的组合条件；失败不会强制交易。

## 12. Forward-Only Progression

`PaperAccount.finalize()` 与 `PaperTradingRuntime.process_session()` 双重禁止回退或重写已封存日期。
相同最终日期只返回原有结果；Finalized 日期缺少对应 Session 会报告状态不一致。

## 13. Clock / Time Semantics

运行时只通过注入的 `PaperClock` 取时，拒绝无时区时间。测试使用 `MutableClock` 提供确定值；所有
生产语义均为时区感知时间。

## 14. OPERATIONAL_REPLAY

Paper Runtime 构造时验证 `AShareExecutionService.availability_mode` 必须是
`OPERATIONAL_REPLAY`，错误配置立即失败。PIT Context 明确使用 RAW 调整模式。

## 15. Daily-Bar V1

V1 是日线 Paper Session：交易日由 PIT Calendar 决定，执行与盯市只使用目标日 PIT 可见
DailyBar。休市日不创建正常 Session。

## 16. Order Intent Timing

`PaperOrderIntent` 保存提交时间、有效交易日、来源、方向、数量和 `NEXT_OPEN`。运行时要求 Intent
在目标 Session 上午开盘前形成，且在当前 Clock 之前已存在。

## 17. Next-Session Fill

Paper 专用 Execution Service 配置 `reference_price_field="open"` 与
`execution_policy_version="next-session-open/v1"`。E2E 精确断言成交价等于目标 Session 开盘价。

## 18. Execution Uncertainty

V1 不模拟盘口、撮合队列或部分成交，不猜测不确定执行顺序。无法获得安全 PIT 证据时拒绝成交或
阻塞 Finalization，而不是补用 future/latest 值。

## 19. Decision Source Boundary

`PaperDecisionSource` 是 Application-owned Protocol；运行时只消费可审计 Intent。确定性测试使用
`ScriptedPaperDecisionSource`，未引入 Strategy/AI/Provider 具体实现。

## 20. NO TRADE

开放交易日允许空 Intent：仍完成 Session、收盘盯市和 Performance Snapshot。Champion E2E 的
Day 1 与 Day 5 覆盖该行为。

## 21. SPEC-006 Integration

委托复用 `AShareExecutionService`、`PreTradeRiskPolicy`、T+1 `SettlementBook`、整手、价格限制、
现金、集中度、费用、税费和审计证据，不复制第二套执行/风险逻辑。

## 22. Multi-Position

Champion E2E 同时持有三只 A 股，验证多标的买入、风险拒绝、T+1 拒绝、部分卖出和完整平仓；每日
状态在 Session 间连续恢复。

## 23. Daily Marking

所有非零持仓在 Finalize 前按目标交易日 PIT 可见收盘价盯市，生成 `EOD_MARK`、
`NAV_SNAPSHOT` 和 `PERFORMANCE_SNAPSHOT` 事件。

## 24. Missing Mark Behavior

缺少任一持仓或 Benchmark 的安全收盘价时，Session 进入 `BLOCKED`、账户进入 `PAUSED`，保留
`MARK_DATA_UNAVAILABLE` 原因事件，且不生成虚假 NAV。

## 25. NAV Series

每个 Finalized OPEN Session 只有一个稳定 Performance Snapshot。无交易日也保存快照；重启后从
恢复投影继续，因此 NAV 序列连续且可比较。

## 26. Drawdown

`calculate_performance()` 计算 Peak NAV、Current Drawdown 与 Max Drawdown，均使用连续历史
Snapshot，不重置高水位。

## 27. Performance Analytics

实现 Total Return、CAGR、Annualized Volatility、Max Drawdown、Sharpe、Sortino、Calmar、
Benchmark/Excess Return、Turnover、Fee/Tax/Slippage 和 Fill Count。

## 28. Metric Definitions

公式、首日基准、252 日年化、风险自由利率、CAGR 自然日门槛与成本恒等式记录在
`docs/performance/PERFORMANCE_BASELINE.md`；配置由 `PaperPerformanceConfig` 版本化。

## 29. Sample Sufficiency

默认少于 20 个收益样本时标记 `INSUFFICIENT_SAMPLE`；CAGR 默认不足 365 个自然日不输出。
测试验证样本从不足转为充分，不把短样本包装为成熟证据。

## 30. Trade Episodes

`derive_trade_episodes()` 只在单标的持仓完成 `0 -> positive -> 0` 后创建 Episode。部分卖出不会
提前结束周期；开放持仓不进入胜率。

## 31. Benchmark / Excess Return

Benchmark 由注入的市场标的定义，并通过同一 PIT Context 获取收盘值。Snapshot 保存 Benchmark
Return 与组合 Total Return 的差值 Excess Return。

## 32. Cost Transparency

快照分别保留 Fee、Tax、Slippage；E2E 验证
`Gross PnL - Net PnL = Fee + Tax + Slippage`，每项可追溯到 Fill/现金账本。

## 33. Restart / Resume

PostgreSQL/Memory Repository 保存完整恢复投影。E2E 在多日中途重建 Runtime，再继续后续日期；
结果与不中断运行一致。Blocked Session 可在证据恢复并显式 Resume 后继续。

## 34. Idempotency

相同 Finalized Session 重复调用直接返回原结果，不新增 Fill、Ledger、NAV 或事件。持久化采用
insert-or-verify：相同证据幂等，身份冲突拒绝。

## 35. Crash Recovery

参数化测试覆盖 RiskDecision 后/Fill 前、Fill 后/Accounting 前、Accounting 后/Snapshot 前、
Snapshot 后/Finalization 前四个故障点。每次故障后持久状态与故障前完全相等，恢复最终结果与基准
运行相等。

## 36. Session Finalization

只有执行、结算、盯市、Benchmark、Performance 和 Episode 均成功后才原子保存 Finalized 状态。
Repository 拒绝删除或修改 Finalized Session 及既有审计证据。

## 37. Corporate Action Safety

运行时在处理 Intent/持仓前查询 PIT Corporate Actions。V1 不支持的公司行动触发
`UNSUPPORTED_CORPORATE_ACTION` 事件并安全暂停，绝不静默忽略。

## 38. Operational Status Events

Domain 枚举支持 IDLE、READY、WAITING_FOR_MARKET_DATA、PROCESSING_ORDERS、RISK_CHECKING、
MARKING_TO_MARKET、FINALIZING、PAUSED、ERROR、STOPPED。事件来自实际 Runtime 状态，不是 UI
动画。

## 39. Future Activation Ceremony

文档固定未来映射：`“大吉大利” -> UI authorization phrase -> ActivatePaperAccount -> readiness
gates -> RUNNING`。短语不具有绕过门禁的权限；本阶段没有 UI。

## 40. Audit Timeline

实际证据覆盖 Account Created/Activated、Session Planned/Open、Order Intent、Eligibility、Risk
Decision、Accepted/Rejected、Fill、Cash/Position/Settlement、EOD Mark、Risk/NAV/Performance
Snapshot 和 Session Finalized。

## 41. Persistence

`PaperTradingRepository` 端口由 Application 所有。Memory Adapter 用于确定性测试；PostgreSQL
Adapter 在单事务内更新账户恢复投影，并写入规范化、可查询、不可变审计证据。

## 42. Migration

`20260904_0010_forward_paper_trading.py` 只新增 SPEC-007 表、约束和索引，未修改历史 migration。
已验证 fresh → head、0009 → 0010、0010 → 0009 → head。

## 43. PostgreSQL Evidence

新增 `paper_accounts`、`paper_account_state_events`、`paper_sessions`、`paper_order_intents`、
`paper_performance_snapshots`、`paper_trade_episodes`。集成测试验证 round-trip、幂等、事务失败映射、
恢复投影损坏、Finalized/append-only/规范化身份冲突。

## 44. Champion E2E

`test_official_champion_multi_day_e2e_restart_and_idempotency` 覆盖 500k 激活、NO TRADE、三标的、
T+1 拒绝、风险拒绝、部分/完整卖出、成本、审计、连续 NAV、重启和重复调用。

## 45. Restart E2E

同一 E2E 在 Day 3 后重新构造 Runtime，继续 Day 4–6，并验证账户初始资本不变、历史快照保留、
最终状态可读取。

## 46. No-Lookahead E2E

`test_closed_market_creates_no_session_and_future_bar_cannot_fill` 与
`test_same_day_complete_bar_cannot_fill_at_same_day_open` 验证未来可用时间的 Bar 不成交、当日完成
Bar 不能回填当日开盘 Intent，且不产生结果证据。

## 47. Performance E2E

Domain 测试验证 20 个样本、CAGR/Volatility/Sharpe、Total/Benchmark/Excess Return；Champion E2E
验证 NAV、持仓数量、成本合计和 Gross/Net 恒等式。

## 48. Replay Determinism

身份由稳定输入经 SHA-256 生成，测试 Clock/Decision/PIT 固定。四个 crash checkpoint 的恢复结果
与无故障基准做对象级全等比较。

## 49. Architecture Tests

`apps/backend/tests/architecture/test_dependencies.py` 验证 Domain/Application 不依赖
Infrastructure/Presentation/Provider/SQLAlchemy，Paper 只经 PIT/Execution 边界工作，禁止 latest、
Tushare、Strategy、AI、Shadow、Radar、Memory、UI、Margin 和 Leverage 依赖。

## 50. Master Requirement Traceability

| Requirement | SPEC-007 Status |
|---|---|
| Champion 500k | Implemented foundation |
| Continuous compounding | Implemented |
| Multiple positions | Implemented / verified |
| Forward Paper Trading | Implemented V1 |
| Research vs Forward isolation | Implemented |
| No-Lookahead | Implemented / verified |
| T+1 | Reused / verified |
| A-share risk rules | Reused / verified |
| NO TRADE | Implemented |
| Performance Dashboard data | Foundation |
| Shadow Portfolios | Deferred |
| Three daily meetings | Deferred |
| Committee Room | Deferred |
| AI Brain | Deferred |
| Multi-horizon | Deferred |
| Multi-asset | Future compatible |
| Kelly | Deferred |
| Leverage | Explicitly disabled |
| Memory | Audit-compatible foundation |
| Governance | Audit-compatible foundation |
| Role Activity Board | Status-event foundation |
| “大吉大利” | Activation-command foundation |
| Learning Lab | Deferred |
| Opportunity Radar | Deferred |
| Alpha Tribunal | Deferred |
| CMRO | Deferred |

## 51. Full Tests

本地隔离 PostgreSQL 上执行 `pytest --cov --cov-report=term`：`549 passed in 59.24s`，无 skip 或
xfail。测试包含 Domain、Application、PIT、PostgreSQL、Migration、Architecture、重启/幂等、
crash recovery 和 Champion E2E。

## 52. Coverage

- 全仓：97.30%；
- Paper Account/Session Domain：100%；
- Paper Runtime：96%；
- Performance/Trade Episode：97%；
- PostgreSQL Paper Adapter：99%；
- 均高于 SPEC-007 的 95% 分项门槛和全仓 90% 门禁。

## 53. Ruff

`ruff check apps/backend/src apps/backend/tests`：Passed。所有本次 Python 文件也通过 Ruff format
检查；仓库历史文件未做无关格式化。

## 54. Mypy

`mypy` strict：`Success: no issues found in 114 source files`。

## 55. WPF

`dotnet build apps/desktop/AIC.Desktop.csproj --configuration Release`：Passed，0 warnings，
0 errors。

## 56. Git Diff

Implementation commit 共 24 个文件、3,855 insertions、6 deletions。删除仅为对 SPEC-006 Execution
硬编码模式/版本的向后兼容参数化；未删除既有功能或迁移。

## 57. GitHub Actions

Implementation HEAD `84f7df01555331478178f5c6b41ba005488ae7e0` 对应
[CI Run 33829974809](https://github.com/steemchen-creator/AIC/actions/runs/33829974809)：
Governance baseline、Backend tests、Desktop build 全部 Passed。提交本报告后会对新的文档 HEAD
再次等待三项 required checks，并在最终交付中给出 exact-HEAD attestation。

## 58. Known Limitations

- V1 只有 DailyBar、NEXT_OPEN、全量成交语义；无盘中撮合和部分成交；
- 公司行动尚无账户级记账，检测到影响时会阻塞；
- Activation Readiness、Decision Source 与 Price Limit Source 是端口，本阶段未提供生产调度/API/UI；
- 无外部出入金、实盘、Broker、AI、策略、融资融券或杠杆。

## 59. Technical Debt

账户恢复投影与规范化证据有意双写以换取原子恢复和可查询审计。随着长期 Track Record 增长，完整
投影体积可能需要基于实际性能数据做分段快照；当前无性能瓶颈证据，因此不在 SPEC-007 预先优化。
数据库不可用时事务回滚并停止处理，数据库恢复后的持久化 PAUSED 仪式留给未来运行编排层。

## 60. Final HEAD Attestation Requirement

报告提交并 Push 后必须满足：Local HEAD = Remote branch HEAD = PR #8 Head；该 exact SHA 对应的
Governance baseline、Backend tests、Desktop build 全部 Passed；Workspace Clean。此动态证明由
最终交付消息提供，且不创建递归修改 SHA 的 evidence-only commit。

## 61. Final Recommendation

`B. APPROVED CANDIDATE WITH NON-BLOCKING DEBT`

建议 Architecture Review 重点确认：Research/Forward 隔离、NEXT_OPEN 时序、PIT/Unknown 行为、
Session 不可变性、原子恢复、绩效口径和公司行动安全阻塞。不得在 Review 前 Merge，不得开始
SPEC-008。
