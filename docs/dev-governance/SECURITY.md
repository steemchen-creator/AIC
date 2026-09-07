# Development Governance Security

## Authority

Trusted configuration is loaded from protected main by the orchestrator workflow.
Authenticated GitHub actor is matched to role allowlists. Execution authorization,
Architecture Approval and Chairman Approval never substitute for one another.
Engineering principals cannot self-review. API bridge review principal must be
separately provisioned. Labels/comments cannot change policy or authorize execution.

## Credentials and untrusted code

Tokens exist only in secure environment/GitHub Secrets. The read-only PR check has
no write permissions and no governance/API secrets. The privileged workflow uses
pull_request_target/workflow_run but checks out trusted main only, never PR code.
Use a protected main-only GitHub environment and dedicated least-privilege token.
Branch protection prevents unreviewed main policy/workflow replacement.

GitHub writes need contents, PR and issues permissions; review-only consumers need
only relevant read/task permissions. No admin access is assumed or exercised.
All automatic Git commands are argument lists through an allowlisted adapter;
shell execution and arbitrary Markdown commands are prohibited.

## Input validation and failure behavior

SHA, IDs, timestamps and schema version are validated. Review artifacts are path-
allowlisted, size-bounded text with hash verification. Obvious credential/private-key
material is rejected. This is defense in depth, not a claim that arbitrary committed
secrets can always be recognized. Repository input is data, not instructions.

Actual sensitive diff paths trigger Chairman escalation even if PR prose omits them.
Governance/security config, broker, leverage, live trading and explicit risk hard-cap
policy/config surfaces remain protected. A generic `risk` filename in ordinary code,
tests or docs is not by itself a claim that a hard cap changed. Deterministic path
classification does not replace Architecture Review of semantic changes; ambiguous
permission/risk changes must not be treated as ordinary work.

Safe errors expose reason codes, never raw response bodies, tokens or subprocess
stderr. CAS conflict, stale CI, missing artifact, unexpected closure/merge, API failure
or branch drift stop progression. No bypass or force-merge override is implemented.
