# Development Workflow

Every change follows this lifecycle:

```text
Idea
  -> Architecture
  -> Task
  -> Codex
  -> Pull Request
  -> Review
  -> Merge
  -> Release
```

## Gates

1. Idea: state the problem and intended outcome.
2. Architecture: assess boundaries, impact, risks, and whether an ADR is required.
3. Task: define scope and verifiable acceptance criteria.
4. Codex: implement only the approved scope on a task-specific feature branch.
5. Pull Request: explain what changed, why, risks, and validation.
6. Review: resolve feedback and obtain required approval.
7. Merge: merge through GitHub only after checks and review pass.
8. Release: record and communicate the approved change.

Direct changes to `main` are prohibited. Every change, including documentation and governance, must pass through a Pull Request.
