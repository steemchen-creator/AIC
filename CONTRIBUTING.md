# Contributing to AIC

## Git flow and branches

- Start every task from the latest `main` on `feature/<task-name>`.
- Keep one coherent task per branch and never commit directly to `main`.
- Push each completed checkpoint to GitHub.

## Commits

Use focused Conventional Commits: `type(optional-scope): imperative summary`. Common types are `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, and `build`.

## Pull Requests and review

- All changes require a Pull Request into `main`.
- Complete the PR template, link the relevant Issue, disclose risks, and provide validation evidence.
- Keep the PR as Draft until its acceptance criteria are met.
- Address review feedback with additional focused commits. Authors do not bypass required review or merge checks.

## Issues

Use the Feature, Bug, or Improvement template. State the problem, context, expected outcome, and acceptance criteria. Security-sensitive reports must not expose secrets or exploitable details in public Issues.

## Coding style

- Follow the language-specific formatter and linter adopted by the repository.
- Prefer clear, small, testable changes over speculative abstractions.
- Handle errors explicitly at system boundaries and avoid silent failures.

## Documentation

Update README, CHANGELOG, affected documentation, and ADRs in the same PR as the change. Documentation is part of the acceptance criteria.
