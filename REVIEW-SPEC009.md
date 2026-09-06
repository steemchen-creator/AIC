# REVIEW-SPEC009

## 1. Executive Summary

SPEC-009 已形成可审核候选：AIC 现在可以在同一个 CNY、long-only、无杠杆 Portfolio 中同时
持有 A 股和境内上市 ETF；纳斯达克暴露通过境内 QDII ETF 表达。指数拥有独立的不可交易参考
身份，只能用于 Benchmark 和 ETF 跟踪关系。所有新增数据和产品规则均受 provenance、PIT、
严格 Normalizer、insert-or-verify persistence 与确定性测试约束。

## 2. Git / Branch / PR

- 基线 main：`c9dde339be1920979cbcdee3ce6969ce3200c780`
- 开发分支：`feature/etf-index-exposure`
- PR Base：`main`
- Draft PR、最终 SHA、Remote/PR Head：在本文件随实现提交后创建并作为 Final HEAD 外部证明报告；
  不制造自引用或 evidence-only commit。

## 3. Scope Confirmation

已实现 ETF/Index Domain、Tushare Adapter、Normalizer、Application ports/services、PIT、
PostgreSQL、迁移、产品级执行规则、asset-aware costs、Champion/Shadow 混合组合和文档。
未实现直接美股、QQQ/QQQM、USD 账户、FX、美国交易日历、AI Brain、Opportunity Radar、
Kelly、杠杆、Memory、Governance 或 UI。

## 4. Official API Verification

2026-09-06 核验官方文档：

- [etf_basic](https://tushare.pro/document/2?doc_id=385)
- [etf_index](https://tushare.pro/document/2?doc_id=386)
- [fund_daily](https://tushare.pro/document/2?doc_id=127)
- [fund_adj](https://tushare.pro/document/2?doc_id=199)
- [etf_share_size](https://tushare.pro/document/2?doc_id=408)
- [index_daily](https://tushare.pro/document/2?doc_id=95)
- [上交所 ETF 交易问答](https://etf.sse.com.cn/fund/quertion/)

核验结论：ETF 日线价格为元、vol 为手、amount 为千元；份额接口 total_share 为万份；
ETF 产品存在 T+0/T+1 差异，不能用单一资产级默认值替代产品证据。

## 5. Architecture Diff

```text
Domain: ETF / Index / Relationship / Valuation / Execution Profile
   ^
Application: ETFDataRepository + ingestion + ETFPointInTimeService
   ^                                      ^
Provider/Normalizer: Tushare           Infrastructure: PostgreSQL
                                           |
Existing Portfolio / Execution / Paper / Shadow reuse the Application boundary
```

新增主要文件：

- `domain/market_data/etf.py`
- `data_foundation/tushare_etf.py`
- `application/ports/etf.py`
- `application/etf.py`
- `infrastructure/etf_persistence.py`
- `migrations/versions/20260906_0013_etf_index_exposure.py`
- ETF/Index/Application/Provider/PostgreSQL 测试与五份专题文档、ADR-0006。

## 6. Asset Classes

`InstrumentType.ETF` 成为第一个真实可执行的第二资产类别；`CASH` 用于兼容资产描述，
`INDEX` 保持非持仓参考类型。原有 Equity 行为回归通过。

## 7. ETF Identity

ETF 身份为 SSE/SZSE + symbol + `ETF`。Domain 拒绝其他市场的 ETF；Instrument Master
现可保存 exchange-listed Equity 或 ETF。

## 8. Index Reference Identity

指数固定使用 `REFERENCE.INDEX` + source-neutral symbol + `INDEX`，不把 Provider 后缀
当作交易场所。

## 9. ETF Master

`ETFMasterBundle` 将现有 `InstrumentMaster`、ETF profile 和可选跟踪关系做一致性校验。
名称、上市/退市、管理人和管理费均保留来源与可用时间。

## 10. ETF Channel / QDII

通道明确为 `DOMESTIC`、`QDII` 或 `UNKNOWN`。分类只来自字段/显式 evidence mapping，
不会从产品名称猜测。

## 11. Benchmark Relationship

`ETFTracksIndex` 保存 ETF、指数、effective range、`current_relationship_only`、provenance
与 `available_at`。上游只有当前关系时不伪造历史。

## 12. Nasdaq Exposure Semantics

`ExposureFamily.NASDAQ` 与 `ExposureCategory.NASDAQ_100` 表示底层暴露。可执行 instrument
仍是境内 CNY QDII ETF，不代表直接 US-market execution。

## 13. ETF DailyBar

`fund_daily` 输出经 RawObservation 和严格 Normalizer 转换为现有 Canonical DailyBar；
event time 为交易日 15:00 Asia/Shanghai 对应 UTC 时刻。

## 14. Volume / Turnover Units

vol 手 ×100 规范化为份；amount 千元 ×1000 规范化为 CNY 元；非整数份量拒绝。

## 15. ETF Adjustment Factor

`fund_adj` 转换为现有 `AdjustmentFactor`，保持 exact Decimal、稳定身份、provenance 和
provider availability。

## 16. ETF Valuation Snapshot

`ETFValuationSnapshot` 保存 NAV、close、share size、premium/discount、trading date、
provenance 与 `available_at`；缺失字段保持 `None`。

## 17. NAV / Share Size

`total_share` 万份 ×10000 规范化为份。NAV 和 close 必须是正 Decimal；share size 非负。

## 18. Premium / Discount

仅在 NAV 和 close 都存在时计算 `(close-nav)/nav*100`。正溢价、负折价和缺失值均有测试；
该字段不产生交易信号。

## 19. Availability / QDII Delay

ETF metadata/relationship/valuation/execution profile 使用 `available_at`；DailyBar 在
Historical Research 使用 provider timestamp、Operational Replay 使用 ingested timestamp。
未来和 Unknown 均不会被当作 Available。

## 20. Index Daily Data

`index_daily` 使用现有 DailyBar 模型，但 instrument 是 `REFERENCE.INDEX`。数据仅供 Benchmark
和跟踪差异计算。

## 21. Execution Profile

`InstrumentExecutionProfile` 按 instrument/effective date 保存 CNY、board lot、settlement、
price-limit reference、calendar、source、availability 和 policy version。

## 22. T0 / T1

明确 T0 才允许当日买入后卖出；T1 到下一个确认开市日释放；Unknown/缺失 profile 拒绝。

## 23. Lot Rules

ETF board lot 从 PIT 可见的产品 profile 读取，不套用所有 ETF 的全局常量。

## 24. Price Limits

继续复用带 `available_at` 的 `PriceLimitBand`。执行证据同时记录 profile 中的规则引用；
缺失/未来/Unknown 安全拒绝。

## 25. Listing / Tradability

ETF 复用 Instrument Master listing lifecycle 和 Trading Status。可执行身份只允许 SSE/SZSE。

## 26. Index Non-Tradability

Index Order 在行情读取前以 `NON_TRADABLE_REFERENCE_INSTRUMENT` 拒绝；指数不进入账户持仓。

## 27. Asset-Aware Fees / Taxes

`ConfiguredAssetFeePolicy` 为 Equity 和 ETF 使用独立配置。所有费用为 Decimal，缺失资产配置
拒绝；版本写入 execution metadata。ETF fixture 不错误套用股票卖出印花税。

## 28. Risk Integration

ETF 复用现有现金、集中度、gross exposure、daily order/fill/turnover、无卖空和无杠杆规则。
新增规则只改变产品事实，不绕开风险链。

## 29. Underlying Exposure Metadata

profile 明确 underlying market/currency、trading currency、exposure category/family。
Unknown 保持 Unknown，不推断。

## 30. Benchmark / Tracking Difference

`calculate_tracking_difference()` 使用同日期 close return 的 exact Decimal 差值并记录 policy
version；Index 可作 Benchmark，不能交易。

## 31. Provider Boundary

Tushare 只负责 HTTP、参数/字段 allowlist 和 Provider error；不导入 Portfolio 或 SQL。
Domain/Application 不包含 Tushare 字段名。

## 32. Validation

RawObservation 先通过 Normalizer 构造严格 Domain；DailyBar 继续通过既有 Validation Engine。
NaN、Infinity、bool、非法日期/市场/状态、错误 capability 和小数份量都 fail closed。

## 33. PIT / No-Lookahead

`ETFPointInTimeService` 提供 profile、relationship、valuation、index reference 和 execution
profile 的 as-of 读取。未来关系、未来估值、未来规则与 Unknown DailyBar 有负向测试。

## 34. Coverage / Backfill

复用现有 `InstrumentCoverageAttempt` / `BackfillAttempt`。ETF Master、DailyBar、Valuation、
Factor、Index Reference 均有 capability-specific attempt 语义。`COMPLETED + received_count=0`
表示已请求且空；无 attempt 表示尚未同步。

## 35. Persistence

Application-owned `ETFDataRepository` 由 PostgreSQL/InMemory Adapter 实现。写入采用
insert-or-verify：同内容幂等，身份相同内容不同返回稳定 conflict，不静默覆盖。

## 36. Migration

0013 新增 `etf_instrument_profiles`、`index_references`、`etf_index_relationships`、
`etf_valuation_snapshots`、`instrument_execution_profiles` 和查询索引。0012↔0013 与
base→head 全链 round-trip 已在 PostgreSQL 17 验证。

## 37. ETF Data E2E

`test_tushare_like_etf_data_runs_raw_to_validated_postgresql_and_pit` 证明 Tushare-like Basic/
Daily/Factor/Valuation/Index → RawObservation → Normalizer → Validation → PostgreSQL → PIT。

## 38. Mixed Portfolio E2E

`test_mixed_equity_domestic_etf_and_nasdaq_qdii_portfolio_is_cny_cash_only` 证明同一 CNY
execution state 同时持有 Equity、境内 ETF、纳指 QDII ETF，且 Index 不成为持仓。

## 39. T0/T1 Evidence

分别验证 T0 当日卖出、T1 当日拒绝/下一开市日释放、Unknown fail closed，并核对 settlement
policy metadata。

## 40. Fee/Tax Evidence

精确用例验证 ETF 买卖成本、零错误税费和 exact net PnL，同时保留 Equity 税费差异。

## 41. Index Gate Evidence

Champion 可用 Index Benchmark；Index Order 被稳定拒绝；ETF-index relationship 可 PIT 查询。

## 42. Premium/Discount Evidence

`test_adjustment_factor_and_valuation_preserve_exact_decimal_units` 覆盖正溢价、负折价、
缺失 NAV/close 和份额单位。

## 43. Nasdaq Fixture

CI 使用去品牌 `CN-listed QDII ETF` 语义 fixture，显式 NASDAQ family/category、CNY trading、
US/USD underlying 和 source-neutral reference index；不依赖真实基金代码或网络。

## 44. Shadow Integration

`test_shadow_member_can_hold_etf_without_cross_account_leakage` 让 Atlas 在同一 Manifest/Policy
下真实买入 ETF，并证明其他三个账户无持仓串扰，Group Comparison 保持正常。

## 45. Multi-Asset Boundary

Implemented：A-share Equity + CN-listed ETF mixed portfolio、CNY accounting、Index benchmark。
Compatible metadata：底层 US/USD 暴露。Not implemented：US instrument execution、USD cash、
FX、US calendar、cross-currency NAV。

## 46. Architecture Tests

29 个 architecture tests 全通过。新增规则证明 Domain 无 Tushare/SQL/UI，Application 无 SQL/
concrete Provider，Provider 不写 Portfolio/DB，Infrastructure 只实现 Application port，Index gate、
PIT、CNY 和范围边界存在。

## 47. Master Requirement Traceability

| Requirement | SPEC-009 Status |
|---|---|
| Multi-asset portfolio | First executable second asset class |
| A-share equity | Existing / verified |
| Domestic ETF | Implemented |
| Broad-market exposure | Implemented foundation |
| Sector ETF | Supported by model |
| Nasdaq exposure | Implemented via CN-listed QDII ETF foundation |
| Direct Nasdaq / US ETF | Deferred |
| Index benchmark | Implemented |
| CNY accounting | Implemented |
| USD accounting | Deferred |
| FX | Deferred |
| ETF T0/T1 | Implemented foundation |
| ETF premium/discount | Data foundation |
| Champion mixed portfolio | Verified |
| Shadow mixed portfolio | Verified |
| Multi-horizon | Deferred |
| Swing / Wave Engine | Deferred |
| Opportunity Radar | Deferred |
| AI Brain | Deferred |
| Kelly | Deferred |
| Leverage | Disabled |
| Memory | Audit-compatible; not implemented/changed |
| Governance | Audit-compatible; not implemented/changed |

## 48. Full Tests

本地 PostgreSQL 17、Python 3.12.10：`630 passed in 72.85s`，无 skip/xfail；branch coverage
总计 `97.40%`。

## 49. Coverage

- ETF/Index Domain：`95.04%`
- ETF Application：`95.35%`；port `100%`
- Tushare ETF Normalizers：`98.12%`
- ETF PostgreSQL additions：`96.20%`
- asset-aware portfolio policies：`100%`
- 全仓：`97.40%`，门禁 90%

## 50. Ruff

`ruff check apps/backend/src apps/backend/tests`：Passed。

## 51. Mypy

`mypy` strict：Passed，124 source files。

## 52. WPF

`.NET SDK 8.0.410`；Release Build：Passed，0 warnings / 0 errors。

## 53. Git Diff

`git diff --check`：Passed。提交前再次检查 staged paths、secret/governance 和完整 diff。

## 54. GitHub Actions

Draft PR 创建后必须等待最终不可变 HEAD 的 Governance baseline、Backend tests、Desktop build。
最终 Run、check conclusion 和三方 SHA 一致性在 PR/交付回复中报告；本文件不使用后续
evidence-only commit 自我改写 HEAD。

## 55. Known Limitations

- Tushare 只提供当前 ETF-index 关系时，历史 effective range 无法伪造；
- IOPV 没有被伪装成 NAV，本阶段只保存已明确提供的估值字段；
- 普通 CI 不访问实时 Tushare；
- 不支持直接 US execution、FX、USD cash、US calendar、cross-currency NAV；
- Provider 修订仍遵循 V1 insert-or-verify，冲突需未来获批 revision policy。

## 56. Technical Debt

非阻塞债务：未来可接入权威产品规则/分类 registry、历史 ETF-index relationship revisions、
独立 IOPV capability 和可选人工授权 live smoke。以上均不影响本阶段类型/PIT/执行安全边界。

## 57. Final HEAD Attestation Requirement

提交后必须同时满足：Local HEAD = `origin/feature/etf-index-exposure` = Draft PR Head；该 SHA
对应的 required GitHub Actions 全部成功；Workspace Clean。证据必须外置报告，避免形成新的
自指证据提交。

## 58. Final Recommendation

`B. APPROVED CANDIDATE WITH NON-BLOCKING DEBT`

在 Architecture Review 前不得 Ready/Merge，不得开始 SPEC-010。
