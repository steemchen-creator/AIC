# REVIEW — SPEC-004 Final Architecture Review & Closeout

## 1. Executive Summary

基于当前 `feature/real-data-foundation` 的真实代码、迁移、测试和 CI，SPEC-004 已形成可审计、
可持久化、Provider-neutral 且具备 PIT/No-Lookahead 约束的 A 股 Real Data Foundation。
本次未发现会导致数据错误、未来泄漏、身份破坏、静默覆盖、密钥泄漏或迁移失败的 Blocking Defect。

## 2. Final Recommendation

**B. APPROVED WITH NON-BLOCKING DEBT**。

## 3. Git / Branch / PR Status

审查基线为 `6c98648cad8718d9ccb021dfe94bc56ad296c186`，分支
`feature/real-data-foundation`，PR #5 为 Draft/Open/Not Merged。Final Review 文档提交后需对
新的文档 HEAD 执行 external immutable attestation。

## 4. SPEC-004 Scope Summary

实现范围从 canonical data、validation、quality、normalization、persistence 和 Tushare daily，
延伸到 historical backfill、calendar、instrument/status、corporate action/factor、adjusted view
以及 PIT/No-Lookahead。未进入 Strategy、Backtest Engine、Portfolio、Paper/Live Trading 或 AI。

## 5. Phase 1–11 Completion Matrix

| Phase | 仓库真实能力 | 状态 | 主要证据 |
|---|---|---|---|
| 1 | Canonical models、identity、provenance、raw hash | Verified | `domain/market_data/models.py`、identity tests |
| 2 | Immutable Validation Engine | Verified | `data_foundation/validation`、validation tests |
| 3 | Deterministic Data Quality Engine | Verified | `data_foundation/quality`、quality tests |
| 4 | RawObservation→Normalizer→Validation/Quality ingestion | Verified | normalization/ingestion modules and tests |
| 5 | Application ports、PostgreSQL insert-or-verify、migration | Verified | canonical persistence and PostgreSQL tests |
| 6 | Tushare A-share DailyBar Provider | Verified | Provider/normalizer/E2E tests |
| 7 | Historical query、coverage ledger、resumable backfill | Verified | historical use cases and PostgreSQL E2E |
| 8 | SSE/SZSE Trading Calendar | Verified | calendar domain/repository/backfill/E2E |
| 9 | Instrument Master、Trading Status、gap classification | Verified | instrument modules and PostgreSQL E2E |
| 10 | Corporate Action、Factor、RAW/front/back adjusted view | Verified | action/factor persistence and adjusted E2E |
| 11 | PIT、availability modes、No-Lookahead、universe baseline | Verified | PIT policy/service and PostgreSQL E2E |

## 6. Provider Runtime Review

Registry、Factory、Lifecycle、Health、Selector、Scoring、Invocation 和 Failover 仍保持 SPEC-003
边界。`ProviderFactory` 使用显式 builder allowlist，无 dynamic import；Lifecycle 是 runtime state
唯一写入口，Health 只通过 Lifecycle 请求变化；Selector/Invocation/Failover 不拥有 Canonical Domain。

## 7. Provider Boundary Review

真实数据路径为 Provider Adapter → immutable provider result → RawObservation → provider-specific
Normalizer → Canonical → Application-owned persistence port。Application/Domain 不引用 Tushare DTO，
Provider 不直接写 PostgreSQL，不存在 Provider row → DB shortcut。

## 8. Canonical Data Review

`DailyBar`、`TradingSessionDay`、`InstrumentIdentity/Master/TradingStatus`、`AdjustmentFactor`、
`CorporateAction` 与 PIT vocabulary 均为 source-neutral value models。证券身份统一使用
`Market + symbol + InstrumentType`，未发现第二套永久证券 ID。

## 9. Units Review

Canonical DailyBar volume 为股，turnover 为人民币元。`TushareDailyBarNormalizer` 明确执行
`vol × 100` 与 `amount × 1000`，Decimal 和 E2E tests 锁定该语义；后续 Provider 必须映射到同一单位。

## 10. Time Semantics Review

`trading_date` 是交易所交易日，DailyBar `event_time` 是常规 15:00 Asia/Shanghai 的日线周期结束，
不是最后一笔成交时间。Domain 要求 aware datetime；PIT 不把 event time 自动当 availability。

## 11. Provenance Review

Canonical facts保留 provider、source identity/URI、raw hash、transformation version 和可用时的
provider timestamp；DailyBar 另有 observed/ingested，其他事实有 retrieved。Adjusted projection
保留 raw record identity、factor 与 `a-share-adjustment/v1`；PIT decision 返回 available_at/source/policy。

## 12. Persistence Review

Repository ports 由 Application 拥有，SQLAlchemy adapters 位于 Infrastructure。Canonical identities
唯一，读取有确定排序，写入为 idempotent insert-or-verify；不同事实共用身份时显式
`IDENTITY_CONFLICT`，无 silent overwrite。Decimal、timezone、nullable Unknown evidence 均有 round-trip tests。

## 13. Migration Chain Review

Revision graph 为单线：baseline → 0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0007。
全新隔离 PostgreSQL 已实际升级到 `20260817_0007`；previous-head downgrade/upgrade tests 全绿。
实际数据库已确认 PIT/range/coverage indexes 和 unique constraints 存在，历史 migration 未被重写。

## 14. Coverage / Backfill Review

Historical range inclusive，chunking 固定且可配置；Runtime request 有 timeout/limit；partial failure 会停止
并记录 structured result，COMPLETED coverage 才能消除 gap，重复执行安全恢复并保持幂等。空响应不被
无条件解释为正常，Calendar/Instrument/Status evidence 参与 gap classification。

## 15. Trading Calendar Review

SSE/SZSE exchange-level OPEN/CLOSED facts 与 instrument suspension 分离。Calendar persistence、coverage、
backfill 和 PIT policy 已验证；Historical Research V1 显式采用 ex-ante policy，临时休市修订列为 debt。

## 16. Instrument Identity Review

Canonical identity exchange-aware，Provider `ts_code` 只在 adapter/normalizer 边界出现；SSE/SZSE 均受支持。
Identity 不携带 display name 或 current listing state，因此不会随供应商当前属性漂移。

## 17. Instrument Master Review

Master 保存 current display name、listing/delisting lifecycle、status、retrieval/provenance。文档明确 current
name 不是历史名称；PIT universe 仅返回 canonical identity。完整 SCD/历史名称不属于本 SPEC。

## 18. Trading Status Review

状态为 TRADING/SUSPENDED/UNKNOWN，属于 instrument/day 层并与 exchange calendar 分离。空 Provider
evidence 不等于 TRADING；Historical gap 与 PIT filtering 使用明确 status evidence，未来补录不会泄漏。

## 19. Corporate Action Review

Canonical model区分 CASH_DIVIDEND、STOCK_DIVIDEND、CAPITALIZATION 等类型，并分别保存 record/ex/pay/
effective dates；金额/比例为 Decimal。Tushare normalizer 只映射有官方字段证据的类型，persistence
幂等、冲突显式，PIT 阻止未来 action 泄漏；未实现账户级结算符合范围。

## 20. Adjustment Factor Review

Factor 为正 Decimal，identity 由 instrument/day 确定，来源、版本和 coverage 可追溯。V1 使用官方 factor，
不从 action 猜测；revision 冲突显式暴露，PIT filtering 阻止未来 factor 可见。

## 21. Raw vs Adjusted Review

Canonical raw DailyBar 始终是 source of truth。RAW/front/back 三种语义固定；只派生 OHLC，volume/turnover
保留 raw；projection identity 引用 raw record 和 adjustment version。缺失 factor 抛出 coverage error，
不会用 raw 冒充 adjusted，也不会修改 raw record。

## 22. PIT Architecture Review

`PointInTimeMarketDataService` 为 Application façade，只依赖 repository ports；`PointInTimeContext` immutable，
不携带 DB/HTTP/Provider。event、provider availability、AIC ingestion/retrieval 与 as_of 明确分离。

## 23. Availability Modes Review

HISTORICAL_RESEARCH 使用可证明的 `provider_timestamp`；OPERATIONAL_REPLAY 对 DailyBar 使用
`ingested_at`、其他事实使用 `retrieved_at`。同一历史事实在两种模式的可见性差异有测试锁定。

## 24. No-Lookahead Review

AVAILABLE/NOT_YET_AVAILABLE/UNKNOWN_AVAILABILITY 三态明确，Unknown 不当 Available。Tests 覆盖 exact
boundary、future DailyBar、event-before/availability-after、action/factor/status leakage 与 listing/delisting。
PIT adjusted 请求显式拒绝，避免普通区间末端因子泄漏。

## 25. Survivorship Bias Review

PIT universe 在 listing 前排除、listing 后包含、已知 delisting boundary 后排除；delisting knowledge 未在
as_of 可用时保守保留并给 warning。它不依赖 current display name，满足基础 survivorship-bias control。

## 26. Backtest-safe Data Contract

SPEC-005 默认安全入口必须是：`PointInTimeMarketDataService + HISTORICAL_RESEARCH + explicit aware as_of +
RAW`。不得绕过 PIT Service 直接使用 ordinary Historical/“latest” rows；未来 PIT-adjusted 必须独立扩展。

## 27. Operational Replay Contract

未来 Paper Trading、Decision Audit 和生产复盘应使用 OPERATIONAL_REPLAY，并记录 decision_time、as_of、
availability mode、adjustment mode 和 policy version，以重放 AIC 当时真实信息集。

## 28. Error Taxonomy Review

Provider Runtime 覆盖 invalid definition/request、unavailable、auth/permission、rate limit、timeout、malformed
response、invocation/failover；Data Foundation 覆盖 normalization/validation/persistence/identity conflict/
coverage incomplete。PIT Unknown 通过 structured result 表达，unsupported adjustment 显式异常；消息 sanitized。

## 29. Observability Review

Runtime/backfill/PIT structured results提供 provider、instrument/range、counts、status、coverage、availability
counts 和 policy metadata，可安全形成日志/metrics。当前尚未建立统一 richer operational metrics/dashboard，列为 debt。

## 30. Security / Secret Hygiene

tracked-file 扫描未发现 `.env`、私钥、证书、日志、缓存或真实 token。仅存在 placeholder `.env.example`；
`AIC_TUSHARE_TOKEN` 由环境/secret store 注入。命中 “PRIVATE KEY” 的文件仅为治理禁令文本，无密钥内容。
Provider errors/logging 不输出 token 或完整 raw payload。

## 31. Architecture Boundary Audit

24 项 architecture tests 证明 Domain 不依赖 Application/Provider Runtime/外层框架，Application 不依赖
Bootstrap/Infrastructure/Presentation/Providers/HTTP/SQL，Provider/Infrastructure 不依赖 Presentation，
Bootstrap 是接口与具体实现的组合层。Desktop 仅为外层 WPF shell，不拥有数据 Domain。

## 32. Duplicate / Dead Architecture Audit

代码搜索只发现一个 canonical `DailyBar`、一个 `InstrumentIdentity`、一个 `DataAvailabilityPolicy` 和一个
`AdjustmentService`；Candidate/Validator/Assessor 是职责明确的协议/服务而非重复模型。未发现废弃 adapter
仍被生产路径调用、duplicate adjustment/availability logic 或 direct Tushare shortcut。

## 33. Determinism Audit

Canonical IDs 使用稳定输入与 SHA-256；repository queries 明确 order；backfill chunk/range、normalization、
quality、adjustment math、PIT filtering/zip 和 coverage calculations 在相同输入下可重复。并发幂等 tests 通过。

## 34. Test Architecture Audit

测试包含 Domain/Unit、Application、Architecture、PostgreSQL Integration、Migration、deterministic E2E 和 CI。
关键语义不只靠 mock：Provider Runtime→Tushare fixture→Canonical/PostgreSQL、Calendar、Instrument、Action/Factor
和 PIT 均有真实 PostgreSQL integration evidence。

## 35. PostgreSQL Final Integration

隔离容器 `postgres:17-alpine` 上 fresh upgrade 至 0007 成功。全量 suite 验证 canonical round-trip、coverage、
calendar、instrument/status、factor/action、PIT queries、downgrade/upgrade；测试后容器会停止并自动删除。

## 36. E2E Final Evidence

完整链由同一全量门禁中的确定性 E2E 组成：

- `test_historical_runtime_tushare_postgresql_e2e_is_ordered_and_idempotent`：Provider Runtime→RawObservation→Normalizer→Canonical DailyBar→PostgreSQL/coverage；
- calendar/instrument/corporate-action E2Es：Calendar、lifecycle/status、action/factor persistence；
- `test_postgresql_point_in_time_e2e_preserves_availability_evidence`：PostgreSQL facts→PIT Service→backtest-safe RAW read。

这些测试共同覆盖规格要求的全链，不实现 Backtest 本身。

## 37. Full Test Evidence

`python -m pytest --cov -q`：458 passed in 40.57s，无 skip/xfail。

## 38. Coverage

全仓 96.93%；Availability Policy 100%，PIT Service 96%，Canonical/Corporate persistence 100%，Calendar
96%，Instrument persistence 97%，Historical/backfill/normalizers 95–100%。未显著下降且超过 90% gate。

## 39. Ruff

`python -m ruff check .`：PASSED。

## 40. Mypy

`python -m mypy --strict apps/backend/src`：PASSED，94 source files。

## 41. WPF

`dotnet build apps/desktop/AIC.Desktop.csproj -c Release --nologo`：PASSED，0 warnings / 0 errors。

## 42. Git Diff Check

审查基线 `git diff --check`：PASSED。Final Review 文档提交前后再次核验。

## 43. GitHub Actions

Phase 11 implementation HEAD `6c98648` 的 Run `32014463828`：Governance baseline、Backend tests、Desktop
build 全部 SUCCESS。Final Review 文档提交产生的新 HEAD 必须重新等待 required CI。

## 44. Known Limitations

V1 不提供完整 Instrument SCD/历史名称、Calendar revision history、PIT-adjusted series、账户级 action
结算、第二 Provider/reconciliation、实时/分钟/Tick/Level-2 或 Backtest/Portfolio/Paper Trading。

## 45. Blocking Defects

**0**。未发现数据正确性、look-ahead、identity、silent overwrite、secret、migration 或架构边界 Blocking。

## 46. Non-Blocking Technical Debt

| Debt ID | Description | Impact | Future SPEC candidate |
|---|---|---|---|
| S004-D01 | Instrument Master 无完整 SCD/历史名称 | 历史展示名不可精确重放，不影响 canonical identity | Instrument Reference Data V2 |
| S004-D02 | Calendar 无临时休市/revision history | 极少数修订需保守解释 | Calendar Revision Policy |
| S004-D03 | Tushare 历史 provider timestamp 覆盖有限 | Historical Research 对无证据行返回 Unknown，安全但可用率下降 | Provider Availability Evidence |
| S004-D04 | PIT-adjusted series 未实现 | Backtest V1 只能安全使用 RAW | PIT Adjustment V2 |
| S004-D05 | 只有一个真实 Provider，无 reconciliation | 无 cross-source 冲突比较 | Multi-Provider/Reconciliation |
| S004-D06 | 统一 operational metrics/dashboard 尚未建立 | 运行诊断粒度有限，不影响 structured result correctness | Observability Foundation |

## 47. SPEC-005 Entry Contract

SPEC-005 可依赖 canonical instrument/DailyBar、PostgreSQL repositories、historical backfill/coverage、calendar、
instrument lifecycle/status、actions/factors、ordinary RAW/adjusted views、PIT Service、Historical Research、
Operational Replay、No-Lookahead baseline、provenance 和 structured errors。它不得绕过 PIT Service 构造
“历史当时信息集”。未来 AI/learning 也只能消费 Canonical + PIT + Provenance，并保存 decision metadata。

## 48. Scope Confirmation

Final Review 只新增审查证据，不修改功能代码。未新增 Phase 12、Strategy、Backtest Engine、AI、Portfolio、
Risk、Paper/Live Trading、Broker、实时/分钟/Tick/Level-2、Institutional Intelligence、News、Financial
Statements、第二 Provider、UI 或商业功能。PR #5 保持 Draft，SPEC-005 未开始。

## 49. Final HEAD Attestation Requirement

本文件提交后必须满足 Final reviewed HEAD = Local = Remote feature branch = PR #5 Head，并确认该 SHA 的
required GitHub Actions 全部 PASSED、workspace Clean。具体 SHA/Run ID 采用最终 Codex 消息作为 external
immutable attestation，禁止 evidence-only commit loop。

## 50. Final Recommendation

**B. APPROVED WITH NON-BLOCKING DEBT**。Blocking Defects：0；Non-Blocking Debt：6。
建议等待 Architecture Review 审核本文件。获得明确 Merge 授权前，PR #5 必须保持 Draft/Not Merged，
不得删除分支或开始 SPEC-005。
