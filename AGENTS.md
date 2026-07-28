# AIC AI Development Handbook

This repository is the Single Source of Truth for AIC (AI Investment Command Center). These instructions apply to human and AI contributors across the repository.

## Project goals

- Current goal: establish a durable, reviewable project foundation.
- Long-term goal: build a complete institution-grade intelligent financial terminal.
- Prefer correctness, auditability, security, and maintainability over short-term speed.

## Development principles

- Work only within the approved task and its acceptance criteria.
- Make the smallest coherent change that solves the stated problem.
- Surface assumptions, tradeoffs, dependencies, and uncertainty before implementation.
- Do not introduce speculative abstractions, technologies, or features.
- Major architecture changes require a written reason, impact analysis, risk analysis, and review before implementation. Record accepted decisions as ADRs.

## Git and branch rules

- Never develop or commit directly on `main`.
- Create one `feature/<task-name>` branch per task from the latest `main`.
- Keep unrelated changes out of the branch.
- At every completed checkpoint, commit and push to GitHub.
- Review staged paths and diffs before every commit.

## Commit rules

- Use focused Conventional Commits: `type(optional-scope): imperative summary`.
- Use `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, or `build` as appropriate.
- Do not mix formatting, refactoring, and behavior changes without a documented reason.

## Pull Request and review rules

- Every change requires a Pull Request targeting `main`; direct merges are prohibited.
- Keep incomplete work in a Draft PR.
- Explain What, Why, Risk, Test, and rollback or migration considerations.
- Link relevant Issues and ADRs. Resolve review feedback with focused follow-up commits.
- Merge only after required review and checks pass. AI contributors must never self-merge.

## Documentation rules

- Documentation is part of the change, not a follow-up task.
- Update `README.md` for setup, usage, structure, or behavior changes.
- Update `CHANGELOG.md` for notable product or development-process changes.
- Update affected files under `docs/` and create or supersede ADRs when decisions change.
- Keep examples sanitized, current, and executable where applicable.

## Coding rules

- Follow adopted language formatters, linters, type checks, and repository conventions.
- Prefer explicit interfaces, narrow responsibilities, and testable units.
- Validate untrusted input at system boundaries and use safe defaults.
- Preserve backward compatibility unless an approved change explicitly breaks it.
- Do not optimize without evidence and a measurable target.

## Logging and exception rules

- Use structured, actionable logs with appropriate levels and correlation context.
- Never log secrets, credentials, tokens, private data, or unnecessary financial data.
- Handle expected errors explicitly. Preserve the root cause and add useful context.
- Do not swallow exceptions, expose internal details to users, or use logs as error handling.

## Third-party interface rules

- Wrap external services behind owned interfaces and document contracts, limits, and failure modes.
- Set explicit timeouts and define retry, rate-limit, idempotency, and fallback behavior before production use.
- Pin or constrain dependencies and review their license, maintenance, and security posture.
- Never embed credentials or depend on undocumented behavior.

## Database rules

- Treat schema and migration changes as reviewed, reversible production changes.
- Define ownership, constraints, indexes, retention, backup, recovery, and compatibility before implementation.
- Use parameterized access and least-privilege credentials.
- Never modify production data or schemas without explicit authorization and a rollback plan.

## Testing rules

- Define verifiable acceptance criteria before implementation.
- Add proportionate tests for new behavior, regressions, boundaries, and failure paths.
- Keep tests deterministic and independent of uncontrolled external services.
- Record the commands and results used to validate each Pull Request.

## Repository safety and prohibited content

- Never commit `.env` files, secrets, credentials, private keys, certificates, logs, caches, generated output, or local editor state.
- Use placeholder-only `.env.example` files when configuration examples are required.
- Never bypass branch protection, review, CI, security controls, or user authorization.
- During Checkpoint 0, do not add business code, APIs, databases, UI frameworks, infrastructure, market data, financial data, or AI integrations.

## AI behavior rules

- Read this handbook and task documentation before changing files.
- State material assumptions and architecture implications before acting.
- Inspect the existing repository and preserve unrelated user changes.
- Do not expand scope, fabricate requirements, hide failures, or claim unverified success.
- Do not expose secrets in prompts, commands, logs, commits, Issues, or Pull Requests.
- Stop after the requested checkpoint, report validation evidence, and wait for review.
