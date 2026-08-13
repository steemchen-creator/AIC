# REVIEW — SPEC-003 Phase 6 Provider Failover

## 1. Git 状态

- Commit：`22cf8070dba9c3f2b1245c9fd47a0766c5e9a3a4`
- Commit Message：`feat(runtime): add provider failover layer`
- Branch：`feature/provider-runtime`
- Draft PR：[PR #4](https://github.com/steemchen-creator/AIC/pull/4)
- PR 状态：Open / Draft / 未合并
- Phase 6 后续阶段：未开始

## 2. 文件变更

新增：

```text
apps/backend/src/aic_backend/provider_runtime/failover.py
apps/backend/tests/provider_runtime/test_failover.py
```

修改：

```text
CHANGELOG.md
apps/backend/src/aic_backend/provider_runtime/__init__.py
apps/backend/src/aic_backend/provider_runtime/errors.py
apps/backend/src/aic_backend/provider_runtime/interfaces.py
apps/backend/src/aic_backend/provider_runtime/models.py
apps/backend/tests/architecture/test_dependencies.py
docs/architecture/PROVIDER_RUNTIME.md
docs/specifications/SPEC-003-Provider-Runtime.md
docs/testing/PROVIDER_RUNTIME.md
```

Phase 6 Commit 统计：11 files changed，542 insertions，1 deletion。

## 3. Failover 架构

```text
ProviderRequestContext + Payload + Registry/Metrics Snapshot
    -> existing ProviderSelector
    -> selected Provider A
    -> existing ProviderInvoker
    -> structured failure
    -> FailoverPolicy
    -> add attempted IDs to Selector exclusions
    -> existing ProviderSelector
    -> selected Provider B
    -> existing ProviderInvoker
    -> final ProviderInvocationResult
```

- `FailoverPolicy` 只判断结构化错误是否允许切换；
- `ProviderFailoverManager` 只编排 Selector、Policy 和 Invocation；
- 备用 Provider 必须由既有 Selector 选择；
- Manager 不复制或修改排序算法；
- Manager 不修改 Registry、Lifecycle、Health、Quality Score 或 Provider 状态；
- Invocation 通过 `ProviderInvoker` Protocol 注入；
- 不依赖具体 Provider 或外部基础设施。

## 4. Policy 规则

允许 Failover：

```text
ProviderTimeoutError
ProviderExecutionError
ProviderUnavailableError
```

默认禁止：

```text
InvalidRequestError
CapabilityNotSupportedError
ProviderInvalidResponseError
其他未明确允许的 ProviderInvocationError
```

不可变 `FailoverDecision` 包含：

```text
should_failover
reason
excluded_provider_ids
next_provider_candidates
attempt_number
```

## 5. Failover Context

不可变 `FailoverContext`：

```text
request_id
capability
original_provider_id
attempted_provider_ids
max_failover_attempts
started_at
```

校验：attempted IDs 不允许重复，最大切换次数不得为负，时间必须包含时区，并且不包含 Provider 实例或敏感配置。

## 6. Attempt 流程

`max_failover_attempts` 表示允许的 Provider 切换次数，而不是总调用次数：

```text
0 -> 仅 A
1 -> A, B
2 -> A, B, C
```

默认值为 `1`。每次失败后，attempted Provider IDs 会合并进 `excluded_provider_ids`，再调用现有 Selector。因此：

- 同一 Provider 不会重复尝试；
- 不存在无限循环；
- preferred 不能绕过 attempted exclusion；
- Selector 继续控制 Capability、状态、健康、冷却、容量和排序。

## 7. 数据一致性与来源

不可变 `FailoverAttempt` 包含：

```text
provider_id
attempt_number
success
error_code
```

成功的最终 `ProviderInvocationResult` 包含最终 Provider ID、有序 attempt history、每次失败的稳定错误代码和 failover count，不会静默替换数据来源。

示例：

```json
{
  "provider_id": "mock_b",
  "failover_count": 1,
  "attempt_history": [
    {
      "provider_id": "mock_a",
      "attempt_number": 1,
      "success": false,
      "error_code": "PROVIDER_TIMEOUT"
    },
    {
      "provider_id": "mock_b",
      "attempt_number": 2,
      "success": true,
      "error_code": null
    }
  ]
}
```

## 8. 错误模型

新增：

```text
FailoverError             PROVIDER_FAILOVER_ERROR
FailoverExhaustedError    PROVIDER_FAILOVER_EXHAUSTED
FailoverNotAllowedError   PROVIDER_FAILOVER_NOT_ALLOWED
```

错误保留 request ID、Capability、attempted Provider IDs、last error、retryable 和稳定 error code。

- 禁止切换的错误成为 `FailoverNotAllowedError`；
- 预算耗尽或没有备用候选成为 `FailoverExhaustedError`；
- last error 保留最后一个结构化 Invocation Error；
- 对外 Failover 消息固定，不拼接 Provider 内部异常详情。

## 9. Failover 与 Retry

- Failover：切换到另一个 Provider；
- Retry：再次调用同一个 Provider。

Phase 6 只实现 Failover。Attempted Provider 会被明确排除，没有同 Provider Retry、Retry Engine、Circuit Breaker 或自动状态恢复。

## 10. 测试与质量证据

```text
Python tests:               151 passed
Provider Runtime coverage:  92.60%
Failover module coverage:   100%
Ruff:                       Passed
Mypy strict:                Passed
Architecture Tests:         Passed
WPF Release Build:          Passed
WPF warnings/errors:        0 / 0
git diff --check:            Passed
```

Failover 测试覆盖：

- Timeout、Execution Error、Unavailable 允许切换；
- Invalid Request、Capability Error、Invalid Response 禁止切换；
- A 失败 B 成功；
- A 失败 B 失败；
- `max=0` 停止；
- `max=2` 执行 A → B → C；
- 无备用候选；
- 不重复尝试 Provider；
- 保留 last error；
- 最终 Provider 与 attempt history；
- 非法 Context 与预算；
- 对外错误不拼接敏感内部信息。

## 11. Architecture Tests

验证 Failover：

- 明确复用 Selector；
- 不 import Registry 实现；
- 不 import Lifecycle 或 Health；
- 不 import concrete Providers；
- 不 import Bootstrap、Presentation 或 Infrastructure；
- 不依赖 FastAPI、Redis 或 SQLAlchemy。

## 12. GitHub Actions

Run：`31480333739`

```text
Governance baseline: SUCCESS
Backend tests:       SUCCESS
Desktop build:       SUCCESS
```

## 13. 已知限制

- Failover 是单进程、单请求内编排，不提供分布式协调；
- Registry 和 Metrics Snapshot 在整个流程中保持初始快照，不实时刷新；
- 不记录持久化 Metrics，只在结果中记录 attempt history 和 failover count；
- 没有真实 Provider，测试使用确定性 Fixture；
- 不实现 Retry、Circuit Breaker、自动 Lifecycle 恢复或学习策略；
- Selector 在排除 attempted Providers 后无候选时返回 Exhausted；
- Policy 是固定错误类型 allowlist，尚无外部配置。

## 14. 规格符合性摘要

| 要求 | 证据 | 结果 |
|---|---|---|
| 复用 Selector | Manager 注入并调用现有 Selector | 符合 |
| 复用 Invocation | 依赖 ProviderInvoker Protocol | 符合 |
| Failover 不是 Retry | attempted IDs 强制加入 exclusions | 符合 |
| 最大切换次数 | 明确预算，默认 1 | 符合 |
| 不重复 Provider | Context 校验与 Selector exclusions | 符合 |
| 允许错误 | Timeout/Execution/Unavailable allowlist | 符合 |
| 禁止错误 | Request/Capability/Invalid Response | 符合 |
| 最终来源可追踪 | result provider_id + attempt history | 符合 |
| 不修改状态层 | 架构测试 | 符合 |
| Runtime coverage >=90% | 92.60% | 符合 |
| Failover coverage >=95% | 100% | 符合 |
| CI | 三项 SUCCESS | 符合 |
| Draft PR | PR #4 Open / Draft | 符合 |

## 15. Architecture Review 请求

请重点判断：

1. `max_failover_attempts` 按“切换次数”解释是否符合预期；
2. 重新 Selection 无候选时归类为 `FailoverExhaustedError` 是否合理；
3. `last_error` 保存结构化异常对象是否满足安全与审计要求；
4. Failover 全程使用同一 Registry/Metrics Snapshot 是否符合一致性预期；
5. Attempt history 只记录稳定 error code、不记录完整错误消息是否充分。

请给出结论：通过、有条件通过或不通过，并区分合并前阻塞项与非阻塞建议。
