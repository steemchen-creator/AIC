# Testing

- [Data Foundation Testing](DATA_FOUNDATION.md)
- [Provider Runtime Testing](PROVIDER_RUNTIME.md)

## SPEC-006 执行与风险

SPEC-006 测试分为 Domain、T+1、Application/PIT、Architecture、PostgreSQL、
Migration 和确定性 E2E。Windows 本地运行数据库测试时，先让子进程可找到 venv 中的
Alembic，再指向隔离测试数据库：

```powershell
$env:PATH = "$PWD\.venv\Scripts;$env:PATH"
$env:AIC_DATABASE_URL = "postgresql+asyncpg://aic:<test-only-password>@localhost:<port>/<db>"
pytest --cov --cov-report=term-missing
```

不得对已有数据卷执行 downgrade/base；迁移往返测试必须使用临时 PostgreSQL 实例。

## SPEC-007 Forward Paper Trading

SPEC-007 增加账户/Session 状态机、NEXT_OPEN 时序、OPERATIONAL_REPLAY/PIT、连续组合、
Performance、无交易日、缺失盯市、公司行动阻塞、幂等、前向约束和四个崩溃检查点测试。
PostgreSQL 测试覆盖原子恢复投影、规范化证据、冲突拒绝以及 0009 与 0010 迁移往返。

Paper Runtime、Paper Domain/Performance 和 Paper Persistence 关键模块要求分别达到至少 95%
覆盖率；全仓仍受项目统一 branch coverage 门禁约束。

## SPEC-008 Shadow Portfolio Experiments

SPEC-008 测试覆盖 Manifest/Policy Hash/Fairness Contract、一个 Champion 加至少三个 Shadow、
独立账户和连续复利、不同 Decision Source 结果、单成员失败隔离、真实 Role Activity 聚合、
重启与确定性重放、短样本保护、多维 Leaderboard、多资产元数据、PostgreSQL round-trip、
insert-or-verify 冲突及迁移 0010/0011 往返。

审计整改测试另外覆盖头像 Update Command、非法引用拒绝、追加式审计、投资状态不变量、PostgreSQL
重启 read-back、六种 Role Activity 状态表达、任务/输出引用、Decision Source ID/版本不一致、
正反成员处理顺序等价、Group projection 中断后的幂等恢复、Comparison Policy 边界和稳定 tie-break。
Experiment Application、Domain 与 PostgreSQL Adapter 的 branch coverage 均不得低于 95%。迁移验证
覆盖 `0010 -> 0011 -> 0010 -> 0011 -> head` 及 `base -> head`，只允许在隔离临时数据库运行。

架构测试禁止 Experiment Domain/Application 依赖 Infrastructure、Presentation、Provider、HTTP 或
SQLAlchemy，也禁止 AI/LLM、策略引擎、Kelly、杠杆、Level2、实时经纪商和 UI 进入本阶段。
