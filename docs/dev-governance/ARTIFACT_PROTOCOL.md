# Artifact Protocol

## Inputs and outputs

SPEC/DEV-GOV Markdown contains scope, non-scope, requirements, tests, quality gates,
review output and stop condition. FIX belongs to its parent work item.
Engineering produces REVIEW-<work-item>.md, code/tests/docs and a Draft PR.

Architecture Results allow APPROVED_CANDIDATE, APPROVED_WITH_NON_BLOCKING_DEBT,
CHANGES_REQUIRED and FINAL_APPROVED. Only the last can satisfy the merge gate.
JSON and Markdown records carry work item, reviewed SHA, review ID/time/role,
blocking items and structured non-blocking debt. Records are append-only.

## Context manifest

REVIEW_CONTEXT.json includes work/base/head, changed files/modules, SPEC/REVIEW,
relevant ADRs, Master Requirement/memory references, tests, coverage, CI, known debt
and questions. Each selected path carries hash, changed and required flags.
Manifest and request payload are stored in state-branch request directories;
the implementation commit does not claim to contain its own final SHA.

Required project memory is supplied even for a new stateless process. Optional
unchanged context can be reused by hash. Content is rehashed before delivery;
missing or mismatched files fail closed. File and total request size are bounded.

## Trust

Only allowlisted text paths are read. Secret paths, .env, caches, generated output,
binaries, traversal and filesystem symlink aliases are denied. Repository text is
untrusted data, never higher-priority instructions or permission to execute commands.

PR body is a human-readable projection: Work Item, SPEC, base/head SHA, REVIEW,
workflow/architecture/CI/merge state and known debt. It is not the state store.

`.github/dev-governance/work-item.json` is the immutable bootstrap descriptor only.
After initialization it is not edited per SPEC. Ordinary PR identity is resolved to
exactly one registered WorkItem from `automation/dev-state` using PR number/branch,
then exact HEAD, SPEC hash and REVIEW path are checked. Missing, partial or ambiguous
mappings fail closed.
