# AIC Repository Development Rules

This repository is the Single Source of Truth for the AIC project.

## Branching and delivery

- Never develop directly on `main`.
- Create a dedicated `feature/<task-name>` branch for every development task.
- At each completed checkpoint, create a Conventional Commit and push the branch to GitHub.
- When the task is complete, open a Pull Request targeting `main`. Never merge directly into `main`.
- Keep commits focused and use Conventional Commits, such as `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, or `build:`.

## Repository safety

- Never commit `.env` files, secrets, credentials, private keys, certificates, logs, caches, build output, or local editor state.
- Use placeholder-only examples such as `.env.example` when configuration documentation is required.
- Review staged changes before every commit to detect sensitive or unrelated files.

## Documentation

- Update `README.md` whenever setup, usage, behavior, or project structure changes.
- Update `CHANGELOG.md` for every user-visible or development-process change.

## Architecture changes

Before implementing a major architecture change, document and communicate:

1. The reason for the change.
2. The affected components and workflows.
3. Compatibility, migration, security, performance, and operational risks.

Implementation may begin only after this assessment has been presented to the project owner.
