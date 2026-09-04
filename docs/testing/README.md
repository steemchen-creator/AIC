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
