# REVIEW — SPEC-004 Phase 11

## 1. Executive Summary
Point-in-Time/As-Of 数据访问、No-Lookahead 控制和保守型历史证券集合已实现。
## 2. Git / PR Status
分支 `feature/real-data-foundation`；PR #5 保持 Draft，未合并。
## 3. Architecture Diff
新增 Application PIT vocabulary、versioned Availability Policy 和 repository-port façade；
新增 nullable provenance persistence 与 migration 0007，不新增 Strategy/Backtest 模块。
## 4. Files
新增 PIT policy/service、migration、Application/PostgreSQL/architecture tests、两份 data docs
和本 Review；同步 README、CHANGELOG、SPEC、架构及 Phase 7–10 相关文档。
## 5. PIT Semantics
PIT 只返回消费者在 aware `as_of` 时有合法证据可见的信息，不等同数据库当前历史快照。
## 6. Event Time vs Availability Time
Event、Provider availability、AIC ingestion/retrieval 与 Research as_of 明确分离；event time
绝不自动视为 available time。
## 7. Availability Policy
各 record type 有窄方法，统一输出 Available/Not Yet/Unknown decision，不使用巨大类型分支。
## 8. Availability Modes
支持 `HISTORICAL_RESEARCH` 与 `OPERATIONAL_REPLAY`，二者不共享隐式 fallback。
## 9. PointInTimeContext
不可变 context 仅包含 aware as_of、mode、adjustment mode 和 policy version，无 DB/HTTP/Provider。
## 10. PIT Market Data Service
Application-owned façade 只复用既有 repository ports，不 import SQL、HTTP 或 Tushare。
## 11. DailyBar PIT
Historical 使用 provider timestamp；Operational 使用 ingested_at；inclusive range、升序且 provenance 保留。
## 12. Corporate Action PIT
公告/行动 provider timestamp 或 retrieved_at 晚于 as_of 时不可见，阻止未来分红送股泄漏。
## 13. Adjustment Factor PIT
因子使用同一 availability 规则过滤；Unknown 不进入可见结果。
## 14. Backtest-safe Adjustment Policy
PIT V1 仅支持 RAW；前/后复权显式 Unsupported，普通全历史复权不得冒充 PIT。
## 15. Instrument Master PIT
集合只返回 canonical identity，不把 current display name 当历史名称，也不声称完整 SCD snapshot。
## 16. Survivorship Bias Controls
上市日前排除；退市只有在 as_of 已知时排除，未知退市证据保守保留并给 warning。
## 17. Trading Status PIT
后来补录的停复牌状态不可泄漏；缺失 provider timestamp 的 Historical 状态保持 Unknown。
## 18. Calendar PIT
Historical V1 显式采用 ex-ante calendar policy；Operational 受 retrieved_at 限制，修订风险已记录。
## 19. Availability Classification
`AVAILABLE`、`NOT_YET_AVAILABLE`、`UNKNOWN_AVAILABILITY` 三态明确，Unknown 不当 Available。
## 20. Availability Provenance
每条 decision 记录 available_at、source 和 policy version，不修改 canonical provenance。
## 21. Policy Version
固定 `point-in-time-availability/v1`；precedence 变化必须升级版本。
## 22. Persistence / Migration
0007 为 Calendar/Master/Status/Factor/Action 增加 nullable provider timestamp 并建立 PIT indexes；
历史 NULL 不回填，DailyBar 复用既有 provider_timestamp/ingested_at。
## 23. Historical Backfill Semantics
今天回填的历史事实不会在 Operational Replay 的过去时点可见；不使用 created_at 伪造证据。
## 24. Historical Research Mode
有历史 provider timestamp 的事实可按该证据参与研究；缺失证据为 Unknown。
## 25. Operational Replay Mode
严格使用 AIC ingested_at/retrieved_at 重放真实运行信息集。
## 26. No-Lookahead Evidence
专项测试覆盖 available 前、精确边界、之后、event 已发生但 availability 尚未来到和 Unknown。
## 27. Corporate Action Leakage Evidence
已测试 known-after-as_of 不可见、known-before_as_of 可见。
## 28. Adjustment Leakage Evidence
已测试 PIT adjusted request 明确失败；不会取用 as_of 后 factor。
## 29. Instrument Universe Evidence
已测试上市前/后、已知退市、未知退市保守行为及 current-name 隔离。
## 30. Trading Status Evidence
已测试未来 suspension evidence 不可见、已知状态可见和 Unknown 保留。
## 31. Architecture Tests
自动验证 PIT Service 无 Tushare/HTTP/SQL/latest shortcut，且不包含 Strategy/Portfolio/Paper Trading。
## 32. PostgreSQL Evidence
provider timestamp 在六类事实中 round-trip，PIT 组合索引和 nullable Unknown 语义由 0007 支撑。
## 33. E2E Evidence
PostgreSQL DailyBar/Factor/Action/Master/Status/Calendar → PIT façade 的确定性 E2E 已通过。
## 34. Test Evidence
`python -m pytest --cov -q`：458 passed in 39.21s，无 skip/xfail。
## 35. Coverage
全仓 96.93%；Availability Policy 100%，PIT Service 96%，专项合计 98.24%；
Canonical/Corporate persistence 100%，Calendar 96%，Instrument persistence 97%。
## 36. Ruff
`python -m ruff check .`：Passed。
## 37. Mypy
`python -m mypy --strict apps/backend/src`：Passed，94 source files。
## 38. WPF
`dotnet build apps/desktop/AIC.Desktop.csproj -c Release --nologo`：Passed，
0 warnings / 0 errors。Docker Compose config：Passed。
## 39. GitHub Actions
最终提交的 exact-HEAD CI 由外部 immutable attestation 记录，避免 evidence-only commit loop。
## 40. Final HEAD Attestation
最终须满足 Local = Remote = PR #5 Head、required CI 全绿且 workspace Clean；SHA/Run ID 外部记录。
## 41. Known Limitations
无完整 Instrument SCD、revision histories、Calendar 临时修订模型或 PIT adjusted series。
## 42. Technical Debt
真实 Provider availability timestamp 覆盖率、PIT 前/后复权和 Calendar revision policy 需独立设计。
## 43. Scope Confirmation
PIT/As-Of、No-Lookahead、Historical/Operational 语义、当前 lifecycle 层级 survivorship 控制和
action/factor 防泄漏已实现。未实现策略、AI 决策、Portfolio、Risk、Paper/Live Trading、
实时/分钟/Tick/Level-2、机构情报、第二 Provider reconciliation 或 UI。PR #5 保持 Draft。
## 44. Final Recommendation
完成 exact Final HEAD CI 后提交 Architecture Review；不得合并 PR #5，不得自行开始 SPEC-004 Final Review。
