# ADR-0007: Autonomous development control plane

- Status: Proposed — implementation authorized by DEV-GOV-001; Architecture Review pending.
- Date: 2026-09-07
- Authority: owner-authorized DEV-GOV-001 V1.0, not self-approval by its implementer.

## Context and decision

SPEC-009 exposed the difference between execution authorization, architecture approval
and publication. Development coordination needs durable, SHA-bound artifacts and
deterministic gates without frequent evidence commits changing the approved PR HEAD.

Add the separate top-level Python package `aic_dev_governance` alongside the existing
Python sources. It shares the existing test/runtime toolchain, but imports no investment
application, domain, provider, database or desktop modules. No business interfaces change.
The package is not imported by `aic_backend`.

Use a pure authenticated event reducer, pure SHA/CI/merge predicates and a persistent
task outbox. Reserve model budget and task identity atomically before external delivery.
Persist the versioned aggregate and immutable events in `automation/dev-state`, never
implementation/main commits. Local tests use atomic file replacement and an exclusive
writer lock; GitHub uses parent-bound commits and non-force fast-forward reference updates.
External delivery uncertainty stops, rather than issuing another billable model request.

Bootstrap is a distinct protected lifecycle entry point, not a normal runtime event. It
operates while every activation switch is OFF, authenticates a trusted Chairman principal
from a protected environment, verifies reviewed HEAD/merge/tree/exact CI/branch cleanup and
non-empty closeout evidence, and may create the absent state branch exactly once. It cannot
dispatch work, merge, request a next SPEC or loop into normal orchestration.

After bootstrap, each ordinary PR must resolve exactly one work item from durable state by
PR number and branch, with exact HEAD and review artifact agreement. The checked-in
`work-item.json` is a static bootstrap descriptor only. Missing, partial or ambiguous state
identity fails closed, preventing one PR from selecting another work item's approval.

Operational failures are separated from governance incidents. Failed exact-HEAD CI,
engineering failure, known-unavailable engineering bridge and pre-mutation GitHub reads are
recoverable after a new HEAD or successful retry and do not require Chairman intervention.
Premature merge, unknown side-effect outcomes, authorization failures and governance
exceptions remain sticky. Risk hard-cap escalation uses explicit governed policy/config
paths and does not match ordinary source/test/document paths merely containing `risk`.

## Alternatives

- PR comments alone: rejected as mutable/untrusted UI signals without transactional state.
- Evidence commits on feature/main: rejected because approval changes its own input SHA.
- Free-form agent chat: rejected for lack of bounded cost, durable state and authority.
- Product database/Celery integration: rejected; development control is a separate concern.
- Normal-run initialization: rejected because an OFF-by-default runtime otherwise creates a
  bootstrap deadlock or requires unsafe temporary activation.
- Checked-in per-PR identity descriptors: rejected because concurrent PRs can overwrite or
  mis-select identity; durable state is the authoritative ordinary-run source.

## Impact and risks

The new check supplements existing Governance baseline, Backend tests and Desktop build.
New runtime state is schema-versioned; no product DB migration or investment behavior changes.
CAS protects concurrent writes, but remote task delivery and state acknowledgement cannot
be one transaction. Reserved/uncertain deliveries require reconciliation, not blind retry.
GitHub unavailable, unknown required checks and mismatched merge trees fail closed.
Branch protection and protected runner credentials are deployment prerequisites; code
cannot protect itself against a repository administrator or a compromised trusted runner.
The protected bootstrap environment and trusted principal mapping are administrative
dependencies. If they are misconfigured, bootstrap fails closed and normal automation
remains disabled; it does not silently fall back to the GitHub event actor.

## Rollout and rollback

Bootstrap stays Draft until review and owner manual merge. Pipeline, API bridge, Ready and
automatic merge remain OFF by default. After a separate Chairman decision, configure a
protected main-only environment, allowlisted principals, least-privilege credentials and
the independent state branch. Run the protected one-shot bootstrap only after verified
post-merge closeout, then start in MANUAL/DRY_RUN under a separate activation decision.
Never auto-merge DEV-GOV-001.

Emergency rollback: disable the repository activation variable and `pipeline_enabled`,
revoke the dedicated bot token, preserve state branch/audit, and resume the existing manual
PR workflow. Restore state from a verified snapshot only through an audited forward repair;
never rewrite event history or revert investment data. No automatic force-merge escape hatch.
