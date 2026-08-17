# REVIEW — SPEC-004 Phase 10

## 1. Executive Summary
A 股公司行动、复权因子与 RAW/前复权/后复权 DailyBar 派生视图已实现。
## 2. Git / PR Status
分支为 `feature/real-data-foundation`；PR #5 保持 Draft，最终 SHA 在推送和 CI 后核验。
## 3. Provider API Verification
开发前核验了 Tushare 官方 `adj_factor`、`dividend` 与通用复权公式文档。`adj_factor`
返回 `ts_code/trade_date/adj_factor`；V1 `dividend` 只映射有明确字段证据的现金分红、
送股和转增，不猜测配股、拆分或合并。
## 4. Architecture Diff
新增 source-neutral Domain facts、Application-owned ports/use cases、Tushare normalizers、
PostgreSQL adapters 和派生 Adjustment Service；Application 不依赖 Tushare。
## 5. Files
新增 Domain、ports、normalizers、use cases、persistence、migration、tests 与两份 data docs；
同步 README、CHANGELOG、架构、测试和相关 Phase 文档。
## 6. Provider Capabilities
新增 `market.adjustment_factor.read` 与 `market.corporate_action.read`，不冒充 DailyBar。
## 7. Adjustment Factor Model
包含 canonical instrument、交易日、正数 Decimal 因子、版本、检索时间与 provenance。
## 8. Corporate Action Model
可表达现金分红、送股、转增、配股、拆分、合并和未知；V1 只生成官方字段可靠支持的前三类。
## 9. Date Semantics
登记日、除权除息日、派息日和生效日分别保存；缺失保持 None，不猜测、不强制交易日。
## 10. Decimal Semantics
因子、金额、价格和比例全部使用 Decimal，Canonical 路径不使用 binary float。
## 11. RawObservation
供应商响应先封装为带哈希与来源的 RawObservation，再进入 Normalizer。
## 12. Normalization
Tushare 字段只存在于专用 normalizer；无网络、数据库或行情修改职责。
## 13. Validation
验证 instrument、确定性身份、日期顺序、正因子、非负金额/比例、时区和 provenance。
## 14. Provenance
保留 provider、source identity/URI、raw payload hash 和 transformation version。
## 15. Repository Ports
Application 拥有 factor 精确/区间查询与 action 精确/区间查询协议，以及 Normalizer 协议。
## 16. PostgreSQL Schema
迁移 0006 新增 `adjustment_factors`、`corporate_actions`，含唯一身份、instrument/date 索引和 provenance。
## 17. Factor Backfill
显式 instrument/range 输入、日期分块、完成 coverage、安全恢复、partial/failed 结构化结果。
## 18. Corporate Action Sync
独立显式同步；普通 Historical read 不触发全市场或单股票网络同步。
## 19. Coverage
仅 COMPLETED factor attempt 建立覆盖；partial/failed 不会掩盖缺口。
## 20. RAW Mode
默认 RAW，现有调用兼容，OHLC/volume/turnover 与 canonical raw 完全一致。
## 21. Forward Adjustment
前复权使用 `raw OHLC × 当日因子 / 请求区间末日因子`，保持末端价格尺度。
## 22. Backward Adjustment
后复权使用 `raw OHLC × 当日因子`，与同一官方因子源和策略版本一致。
## 23. Volume Policy
V1 不调整 Volume，派生视图保留原始成交量。
## 24. Turnover Policy
V1 不调整 Turnover，派生视图保留原始成交额。
## 25. Adjustment Version
固定为 `a-share-adjustment/v1`；未来语义变化必须升级版本。
## 26. Historical Service Integration
新增可选 `adjustment_mode`，默认 RAW；非 RAW 调用注入的 Adjustment Service。
## 27. Missing Factor Behavior
任一 Bar 缺少因子即抛出 `AdjustmentCoverageIncomplete`，不返回 RAW 冒充复权数据。
## 28. Identity / Idempotency / Conflict
身份确定性；重复写入 `ALREADY_EXISTS`；同身份不同事实 `IDENTITY_CONFLICT`，不覆盖。
## 29. Revision Limitation
V1 为 insert-or-verify，不实现供应商修订历史；修订以冲突暴露，等待独立策略。
## 30. Instrument Integration
复用 Phase 9 exchange-qualified `InstrumentIdentity`，不建立裸供应商代码身份体系。
## 31. Calendar Integration
复用 Phase 8 日历作为背景；登记日和派息日不被强制为 OPEN 日。
## 32. Error Mapping
Runtime/Persistence 保留既有结构化错误；Normalizer/coverage 使用明确、净化的错误类型。
## 33. Observability
结果仅包含 provider/capability/range/count/status；不记录 token 或 raw payload。
## 34. Migration Evidence
自动化测试执行 previous head → 0006、downgrade → previous head、upgrade → head。
## 35. PostgreSQL Evidence
覆盖 round-trip、排序、缺失查询、幂等、身份冲突、factor/action read-back。
## 36. E2E Evidence
Provider Runtime → RawObservation → normalizers → PostgreSQL → Historical Service 的确定性 E2E 通过。
## 37. Architecture Tests
自动验证 Application 无 Tushare/HTTP/SQL、Provider 无 DB、ports/Application 与 PostgreSQL/Infrastructure 归属。
## 38. Test Evidence
`python -m pytest --cov -q`：446 passed in 37.38s，无 skip/xfail。
## 39. Coverage
全仓 96.88%；Adjustment Service 100%，Corporate Action/Factor normalizer 100%，
Corporate Action Domain 99%，Application backfill 96%，Phase 10 PostgreSQL additions 100%，
Historical adjusted integration 97%。
## 40. Ruff
`python -m ruff check .`：Passed。
## 41. Mypy
`python -m mypy --strict apps/backend/src`：Passed，92 source files。
## 42. WPF
`dotnet build apps/desktop/AIC.Desktop.csproj -c Release --nologo`：Passed，
0 warnings / 0 errors。
## 43. GitHub Actions
最终提交推送后的 exact-HEAD GitHub Actions 由外部 immutable attestation 记录，避免
为了写回 Run ID 产生 evidence-only commit loop；required jobs 必须全部 PASSED。
## 44. Final HEAD Attestation
最终核验必须满足 Local = Remote = PR #5 Head、required CI 全绿且工作区 Clean；
具体 SHA 与 Actions Run ID 在本文件对应提交完成后由外部证明提供。
## 45. Known Limitations
无完整 revision history、配股认购模型、拆分/合并映射、第二 Provider reconciliation 或账户级结算。
## 46. Technical Debt
公司行动修订策略、更多官方 action 类型和 factor/action 轻量交叉检查需独立审查。
## 47. Scope Confirmation
A-share Corporate Action、Adjustment Factor、RAW/前复权/后复权基础已实现；raw canonical
DailyBar 不变。未实现实时/分钟/Tick/Level-2、策略、AI 决策、Portfolio 公司行动记账、
Paper/Live Trading、机构情报、第二 Provider 对账或 UI。PR #5 保持 Draft。
## 48. Final Recommendation
完成 exact Final HEAD CI 后提交 Architecture Review；不得合并 PR #5，不得开始 Phase 11。
