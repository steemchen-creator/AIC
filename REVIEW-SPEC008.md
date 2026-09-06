# REVIEW-SPEC008

## 1. 审核结论建议

- 规格：`SPEC-008-Shadow-Portfolios-Multi-Asset-Compatibility-Foundation.md`
- 分支：`feature/shadow-portfolios`
- Base：`main`
- Draft PR：[#9](https://github.com/steemchen-creator/AIC/pull/9)
- 建议：进入 Architecture Review；不得在通过审核前 Merge，不得开始 SPEC-009。

本阶段建立了 Champion 与至少三个 Shadow Portfolio 的公平实验基础。实现复用 SPEC-007 Paper
Runtime 和 SPEC-006 执行/风险边界，没有复制交易引擎，也没有加入 AI、策略引擎、UI 或海外交易
规则。

## 2. SPEC-007 Closeout 证据

- PR #8：`MERGED`
- PR #8 Merge Commit：`62f7829ae467f9942d3f70a1996b31ce635aa94d`
- Closeout 时 Local `main` = `origin/main` = 上述 SHA
- 本地和远端 `feature/forward-paper-trading` 已删除
- SPEC-008 分支由该最新 `main` 创建

## 3. Architecture Diff

```text
domain.experiments
  immutable Manifest / Policy Bundle / Fairness Contract
  member, role/profile, asset compatibility metadata
  group-session result, role activity, comparison and leaderboard

application.experiments
  create group -> create and activate independent Paper accounts
  run group session -> stable per-member execution with failure isolation
  build comparison -> sample-gated multi-dimensional result
                  |
                  v
application.ports.experiments
  ExperimentPaperRuntime / ShadowExperimentRepository / ExperimentClock
             ^                            ^
             |                            |
PaperTradingRuntime              InMemory/PostgreSQL adapter
```

依赖方向仍为 Application/Domain 向内；SQLAlchemy 只存在于 Infrastructure。实验 Application 通过
`ExperimentPaperRuntime` 端口复用 Paper Runtime，不读取 Historical Repository，不接触 Tushare，
也不绕过 PIT Service。

`PaperTradingRuntime.create_champion()` 保持行为兼容，并委托新的通用 `create_account()`。通用入口只
负责独立账户初始化，稳定 account reference 若对应不同名称或初始资金会拒绝，不改变 NEXT_OPEN、
PIT、风控、成本、记账或状态机语义。

## 4. 规格范围对应

| 要求 | 实现证据 |
|---|---|
| ShadowExperimentGroup | `ExperimentManifest` + `ShadowExperimentRecord` |
| Champion + Shadow membership | `PortfolioRole`、`ExperimentMember`，验证恰好一个 Champion、至少三个 Shadow |
| 独立组合与连续复利 | 每个成员有唯一 Paper Account/Portfolio；复用 Paper Runtime 的连续状态 |
| Experiment Manifest | `ExperimentPolicyBundle`、成员、创建时间和资产范围不可变 |
| Fairness Contract | `FairnessContract` 绑定成员、Policy Hash、相同初始资金和九项共享维度 |
| Decision Source | `SCRIPTED`、`MANUAL`、`FIXTURE` assignment；运行时校验 source ID |
| Group Trading Session | `ShadowExperimentService.run_session()` |
| Failure isolation | 单成员异常转为稳定失败结果及 ERROR activity，循环继续其他成员 |
| Deterministic comparison | 稳定 ID、成员排序、同分 account ID 破序、相同日期幂等返回 |
| Performance comparison | `PerformanceComparisonSnapshot` |
| Multi-dimensional leaderboard | 收益、Sharpe/Sortino/Calmar、回撤、成本共同参与综合顺序 |
| Sample sufficiency | `INSUFFICIENT_SAMPLE`、`PROVISIONAL`、`QUALIFIED`；未达标无正式 winner |
| Role/Profile/Avatar | `ManagerProfile` + `RoleIdentity` + `avatar_reference` |
| Role activity aggregation | 只从实际 READY/PROCESSING/WAITING/ERROR 事件聚合最新状态 |
| Multi-asset compatibility | `AssetClass`、`MarketVenue`、`Currency` 元数据，不创建 `AStockPortfolio` |
| PostgreSQL | 恢复投影 + 五类规范化 evidence 表；insert-or-verify |
| Migration | `20260906_0011`，可逆到 `20260904_0010` |

## 5. 公平性与独立性证明

E2E fixture 创建：

- Champion
- Shadow Atlas
- Shadow Sage
- Shadow Aegis

四个账户初始资金均为 500,000 CNY，共用同一 Policy Bundle、PIT cutoff、日历、执行、风控、费率、
滑点和 Benchmark。四个稳定 account ID 和 portfolio ID 均不同。不同 Fixture Decision Source 形成
不同持仓和四个不同 NAV；第二交易日重启 Service 后继续原现金、持仓和 NAV，而不是重置本金。

隔离测试令 Sage Decision Source 抛出异常：Sage 记录 `FAILED/ERROR` 且没有 Performance；Champion、
Atlas、Aegis 仍全部完成并保存各自 Performance。缺失或 source ID 不匹配同样只失败被分配成员。

## 6. 比较语义

每个比较快照保存：

- NAV、Return、Drawdown；
- Sharpe、Sortino、Calmar；
- Benchmark、Excess Return；
- Turnover、commission/tax/slippage 总成本；
- Exposure、Cash、Position Count；
- Sample Sufficiency。

Leaderboard 不是只按收益排名。短样本下 `qualified_winner_account_id = None`。即使后续达到
`QUALIFIED`，该字段也只是可审核比较结果，不会自动替换 Champion、分配资金或触发晋升。

## 7. 数据库与迁移

新增表：

- `shadow_experiment_groups`
- `shadow_experiment_members`
- `shadow_group_sessions`
- `shadow_comparison_snapshots`
- `shadow_role_activities`

Group row 保存原子 recovery projection；规范化表保存查询和审核证据。Manifest/Fairness Contract
不可变，Session/Comparison/Activity append-only，重复相同写入幂等，身份冲突拒绝。

Migration round-trip 已在一次性 PostgreSQL 17 容器验证：`0010 -> 0011 -> 0010 -> head`。降级会删除
SPEC-008 实验证据，不删除既有 Paper Account；非隔离环境执行前必须备份并再次授权。

## 8. API、依赖与兼容性影响

- HTTP API：无新增、无修改。
- 第三方 Python 依赖：无新增。
- WPF：无功能或 UI 修改。
- 现有 Champion API：兼容。
- 现有 SPEC-005/006/007 执行结果：不变。
- PostgreSQL：新增五张表和三个索引。

## 9. 修改文件

核心代码：

- `apps/backend/src/aic_backend/domain/experiments/__init__.py`
- `apps/backend/src/aic_backend/domain/experiments/models.py`
- `apps/backend/src/aic_backend/application/experiments.py`
- `apps/backend/src/aic_backend/application/ports/experiments.py`
- `apps/backend/src/aic_backend/infrastructure/experiment_persistence.py`
- `apps/backend/src/aic_backend/application/paper.py`
- `migrations/versions/20260906_0011_shadow_portfolios.py`

测试与质量：

- `apps/backend/tests/experiments/test_experiment_domain.py`
- `apps/backend/tests/experiments/test_shadow_experiment_service.py`
- `apps/backend/tests/infrastructure/test_experiment_postgresql.py`
- `apps/backend/tests/architecture/test_dependencies.py`
- `pyproject.toml`

文档：

- `README.md`
- `CHANGELOG.md`
- `docs/adr/ADR-0005-shadow-portfolio-experiments.md`
- `docs/experiments/SHADOW_PORTFOLIOS.md`
- `docs/performance/SHADOW_COMPARISON.md`
- 文档索引、数据库与测试说明
- `REVIEW-SPEC008.md`

## 10. Test Evidence

本地最终预提交验证环境：Windows、Python 3.12.10、PostgreSQL 17 临时无卷容器、.NET 8。

| 门禁 | 命令/结果 |
|---|---|
| 全部 Python 测试 | `pytest --cov --cov-report=term-missing`：563 passed |
| 全仓 branch coverage | 96.87%，门槛 90% |
| Experiment Application | 94% |
| Experiment Domain | 91% |
| Experiment Port | 100% |
| Experiment PostgreSQL Adapter | 98% |
| Architecture Tests | 28 passed（包含 SPEC-008 边界） |
| Ruff | `ruff check apps/backend/src apps/backend/tests`：Passed |
| Mypy strict | `mypy`：119 source files，Passed |
| WPF Release Build | Passed，0 warnings / 0 errors |
| Docker Compose config | 设置 test-only password 后 `docker compose config --quiet`：Passed |
| PostgreSQL health | `pg_isready`：accepting connections |
| Migration | 0010/0011 downgrade/upgrade/head：Passed |

Windows 本地全量测试需把 `.venv/Scripts` 加入 PATH，因为旧测试通过裸 `alembic` 子进程执行迁移。
未设置 PATH 的第一次尝试为环境 setup failure，补齐后同一完整测试集 563/563 通过。

## 11. 安全与边界检查

- 未提交 `.env`、密码、Token、证书、日志、缓存或构建产物；
- 测试数据库只使用一次性 test-only credential 和无持久卷容器；
- 未引入 AI Brain、LLM、Investment Committee、会议、Opportunity Radar、Kelly、资本分配、杠杆、
  保证金、做空、实时交易、经纪商、Level2、Memory Retrieval、Learning Lab、Governance UI 或 UI；
- 未实现海外市场日历、换汇、交易时段、结算或监管规则；
- 未实现 Shadow 自动晋升或自动资金分配。

## 12. 已知风险与非阻塞债务

- V1 Group 与各 Paper Account 分别持久化，跨 aggregate 不提供分布式事务；Paper Session 幂等使
  Group 保存重试可恢复，未来如引入跨服务部署需另行设计 Outbox/Saga。
- Multi-asset 仅为兼容元数据；现有可执行路径仍为 A 股/CNY。任何 USD、海外市场或多币种会计必须
  在独立规格中定义汇率、日历、费用、税务和结算规则。
- Comparison 阈值当前由确定性的 `ComparisonPolicy` 提供；生产启用前应由独立治理决策批准具体
  样本门槛，但不得绕开 `QUALIFIED` 保护。

## 13. Final HEAD / CI 说明

本文件属于待提交树，无法在不产生自引用新提交的情况下把自身最终 Commit SHA 写入自身。最终
Local HEAD = Remote Branch HEAD = PR Head、对应 GitHub Actions Run 和 required checks 状态，应以
PR #9 live checks 及交付回执中的 exact SHA 为不可变证明。只有该 exact HEAD 的全部 required checks
通过，SPEC-008 才可提交 Architecture Review。
