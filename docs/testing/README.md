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
