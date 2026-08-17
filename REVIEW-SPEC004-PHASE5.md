# SPEC-004 Phase 5 架构审核证据

## 1. 执行摘要

Phase 5 已建立 Application 所有的持久化端口、PostgreSQL 适配器、Alembic 正式
迁移和幂等存储语义。DailyBar、Provenance 与首次摄取时 Quality Snapshot 在一个
事务、一行记录内原子持久化。本阶段没有接入真实 Provider，也没有开始 Phase 6。

## 2. Git 与 PR 状态

- 分支：`feature/real-data-foundation`
- PR：[Draft PR #5](https://github.com/steemchen-creator/AIC/pull/5)
- 实现证据提交：`313c2d46f4eebd0211338f9d69fc8443234f334e`
- 实现 CI：`31689192504`，全部通过
- 包含本 Review 的最终 HEAD、远端 HEAD、PR Head 与最终 CI 将在 PR 不可变时间线
  和最终交付消息中证明，避免文档提交自引用造成无限证据提交。

## 3. 架构变化

新增依赖方向：

```text
IngestionSuccess
  -> Application PersistIngestionSuccess
  -> Application CanonicalDailyBarRepository Port
  -> Infrastructure PostgreSQL Adapter
```

Domain、Validation、Quality、Normalizer 未依赖持久化技术。

## 4. 文件清单

新增核心文件：

- `application/ports/persistence.py`
- `application/use_cases/persist_ingestion.py`
- `infrastructure/canonical_persistence.py`
- `migrations/env.py`
- `migrations/versions/20260813_0001_canonical_daily_bars.py`
- PostgreSQL/Application 测试文件

同时更新 CI、依赖、README、CHANGELOG、SPEC、架构、测试、数据库、部署与测试配置文档。

## 5. 持久化架构

V1 采用单 Repository 持有事务的最小方案，不增加 Unit of Work 抽象。一次 INSERT
同时保存事实、来源和质量快照，因此不存在子表部分成功。

## 6. Repository Port

`CanonicalDailyBarRepository` 是 Application-owned async Protocol，仅暴露 `save()`
和 `get_by_record_id()`。它不暴露 SQLAlchemy session、Table、Row 或 SQL。

## 7. PostgreSQL Adapter

`PostgreSQLCanonicalDailyBarRepository` 位于 Infrastructure，使用注入的 AsyncEngine。
每次保存使用 `engine.begin()`，每次读取使用短连接上下文；Engine 的 dispose 属于
应用/测试生命周期所有者。

## 8. Schema 与 Migration

Alembic revision `20260813_0001` 创建 `canonical_daily_bars`。迁移可升级、可降级；
CI 证明 fresh upgrade 成功且重复 `upgrade head` 无破坏性副作用。

## 9. DailyBar 存储

保存 record/schema、market/symbol/type、trading_date、三个时间戳、OHLC、volume、
turnover。`record_id VARCHAR(64)` 为主键和最终唯一性防线。

## 10. Decimal 精度

OHLC 使用 `NUMERIC(28,10)`，turnover 使用 `NUMERIC(38,10)`，Quality 分数使用
`NUMERIC(5,2)`。适配器不执行 Domain Decimal rounding；越界由数据库拒绝并回滚。

## 11. Provenance

完整保存 provider/source ID、source URI、provider timestamp、failover 标记/次数、
raw hash 和 transformation version，并与同一 canonical row 原子关联。

## 12. Quality Snapshot

保存总分、四个分项分数和 flags。V1 保留第一次摄取快照；重复事实即使传入不同
Quality 也返回 ALREADY_EXISTS，不覆盖首次快照，不建立历史表。

## 13. Raw Payload 策略

V1 不永久保存完整 raw payload。审计链保留 `observation_id`、`provider_id`、来源标识
和 Phase 1 SHA-256 `raw_payload_hash`，避免无边界保存原始外部数据。

## 14. 幂等与唯一约束

使用 PostgreSQL `INSERT ... ON CONFLICT DO NOTHING`，而不是 SELECT-before-INSERT。
数据库主键处理并发竞争；冲突后读取已有事实进行精确比较。

## 15. Duplicate 语义

首次保存返回 `INSERTED`。同 record_id、同金融事实返回 `ALREADY_EXISTS`，最终行数为
1；Quality 或 provenance 差异不会更新首次存储内容。

## 16. Identity Conflict

同 record_id 但事实字段不同会抛出稳定 `PERSISTENCE_IDENTITY_CONFLICT`。不存在
UPDATE、upsert overwrite、last-write-wins 或静默忽略。

## 17. Transaction / Unit of Work

一行模型加 `engine.begin()` 保证 DailyBar、Provenance、Quality Snapshot 全部提交或
全部回滚。这是当前单聚合写入的最小充分方案。

## 18. Read-back

`get_by_record_id()` 完整重建 InstrumentIdentity、DailyBar、DataProvenance 和
DataQualityAssessment。测试证明 Decimal、date、timezone、flags 和 ID 往返保持。

## 19. Pipeline Integration

`PersistIngestionSuccess` 接受 Phase 4 typed result。成功结果只转换为持久化聚合并
保存，不重新 normalize、validate 或 assess；Pipeline 本身没有 PostgreSQL 依赖。

## 20. Zero-write 证据

Application 测试证明 `IngestionFailure`（覆盖 Normalization/Validation 失败共同结果
类型）直接返回 None，Repository `save` 调用次数为 0。

## 21. 并发

真实 PostgreSQL 测试并发启动两个 writer 保存同一 record_id：结果恰为一个
INSERTED、一个 ALREADY_EXISTS，最终数据库行数为 1。

## 22. 错误分类

稳定分类包括 UNAVAILABLE、CONSTRAINT_VIOLATION、IDENTITY_CONFLICT、
SERIALIZATION_ERROR、TRANSACTION_ERROR。编程 RuntimeError 不在捕获范围内。

## 23. Secret Safety

数据库 URL 只来自 `AIC_DATABASE_URL`。错误向上返回固定安全消息，不包含连接串、
密码或 raw SQL；测试使用带 secret 的失败 URL 并验证消息未泄漏。

## 24. Connection Lifecycle

Repository 不创建全局连接；注入 Engine、按操作获取连接/事务。测试 fixture 在结束时
dispose engine 并在用例间清空表。CI 密码是临时测试服务值，不提交生产凭证。

## 25. Contract / Integration / Migration Tests

- 内存契约：insert、duplicate、read、missing、identity conflict、首次快照不变
- PostgreSQL：round-trip、row count、identity conflict、并发 duplicate、数值越界回滚
- 失败：不可用数据库、安全消息、五类错误映射
- 迁移：fresh migration + repeated migration
- Application：失败零写入、成功单次写入

## 26. 架构审核

18 项 AST 架构测试通过，证明纯层无 SQL 技术依赖、Infrastructure 实现 Application
Port、无 Presentation/Provider Runtime 耦合、无网络/Retry/Reconciliation/Strategy。

## 27. 质量门禁

实现 CI Run `31689192504`：

- PostgreSQL 17 + Alembic：通过
- pytest：`310 passed`，无 skip/xfail
- 总覆盖率：`96.06%`
- PostgreSQL adapter：`100%`
- persistence orchestration：`100%`
- Ruff：通过
- Mypy strict：通过（67 个源文件）
- Architecture Tests：18 passed
- WPF Release Build：0 warning / 0 error
- git diff --check：通过

## 28. Final HEAD 证明

最终 Review-containing HEAD 无法在自身文件中写入自己的内容哈希。最终提交推送后，
将等待该 SHA 的 Governance、Backend/PostgreSQL、Desktop 全部通过，并在 PR #5
不可变时间线记录：Final HEAD == Remote HEAD == PR Head、Run ID 与 Workspace Clean。

## 29. 已知限制与技术债

- V1 仅持久化 DailyBar；没有通用 EAV。
- Quality 是首次快照，没有历史版本。
- 不保存完整 raw payload。
- 本机 Docker Desktop 引擎无法启动，真实 PostgreSQL 证据由 GitHub Actions 的
  PostgreSQL 17 服务提供；这不影响 CI 证据，但本地 Docker 环境仍需独立修复。
- 备份、保留、生产恢复策略仍需部署评审。

## 30. 范围确认与最终建议

- Phase 6 未开始，未选择或接入真实 Provider/API/credential。
- 未实现 Reconciliation、Retry、投资策略、AI 判断、机构资金分析、交易、Portfolio。
- Redis 不是 canonical truth。
- SPEC-003 未修改；Validation 规则未修改；Quality 公式未修改。
- PR #5 保持 Draft，不合并。

建议将 Phase 5 提交架构审核。审核通过前停止，不开始 Phase 6。
