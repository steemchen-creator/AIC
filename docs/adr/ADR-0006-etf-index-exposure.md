# ADR-0006：境内 ETF 与指数参考架构

- 状态：Accepted
- 日期：2026-09-06
- 范围：SPEC-009

## 原因

AIC 需要在现有 A 股现金账户、PIT 和执行基础上支持第一个可执行的第二资产类别，同时必须
守住指数不可交易、QDII 不等于直接美股、产品规则不能靠资产类别猜测的边界。

## 决策

1. `ETF` 成为独立 `InstrumentType`，仅使用 SSE/SZSE 上市身份和 CNY 账本。
2. `INDEX` 使用独立 `REFERENCE.INDEX` 命名空间并永久不可交易。
3. ETF 主数据、指数参考、跟踪关系、估值与执行 profile 是来源中立的 Domain facts；
   Tushare 字段只存在于 Provider/Normalizer 边界。
4. ETF 执行必须选择 PIT 可见的产品 profile；T0/T1、board lot、price-limit reference 与
   asset-aware fee policy 都进入版本化审计证据。未知规则安全拒绝。
5. 复用现有 PIT、Provider Runtime、Repository、Coverage、Portfolio、Paper 与 Shadow
   边界，不建立第二套事件、回填、组合或执行系统。

## 影响

- A 股和境内 ETF 可以在同一个 CNY Portfolio 中执行、估值和比较；
- Champion 与 Shadow 可以持有 ETF，账户隔离与公平 Manifest 不变；
- 指数可以作为 Benchmark 或跟踪目标，但不能进入订单；
- 新增 PostgreSQL 表和可逆迁移 0013。

## 风险与控制

- 上游 ETF/指数关系可能只有当前快照：用 `current_relationship_only` 明示，不伪造历史；
- QDII 数据延迟：PIT 按真实可用时间排除未来数据，未知时安全阻断；
- 产品交易规则差异：强制产品级 execution profile，缺失/Unknown 拒绝；
- Provider 字段和单位漂移：显式 allowlist、严格 Normalizer、确定性 fixture 和单位测试；
- 误解为直接美股能力：文档和类型边界明确禁止 USD/FX/US execution。

## 未采用方案

- 把 ETF 当作 Equity：无法审计产品级结算、费率和底层暴露；
- 把指数当作可交易 instrument：会混淆 Benchmark 与订单资产；
- 根据名称自动识别 QDII/纳指：不可审计且易误分类；
- 为 ETF 创建独立 Portfolio 或回填框架：重复现有边界并扩大本阶段范围。

## 回滚

在 PR 合并前可直接关闭分支。合并后如需回滚，先停止 ETF 写入和执行，再回退应用版本并将
Alembic 从 0013 降级至 0012；迁移会删除本阶段新增表，不影响既有 Equity、Paper 或 Shadow 表。
