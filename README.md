# AIC

机构级A股智能金融终端

## Repository governance

This GitHub repository is the Single Source of Truth for AIC. Development takes place on dedicated `feature/*` branches and reaches `main` only through Pull Requests.

Detailed development and security rules are maintained in [AGENTS.md](AGENTS.md). Project changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## Repository structure

```text
AIC/
|-- .github/
|   |-- ISSUE_TEMPLATE/       # Feature, bug, and improvement intake
|   |-- workflows/            # Continuous integration definitions
|   |-- CODEOWNERS            # Review ownership
|   `-- PULL_REQUEST_TEMPLATE.md
|-- docs/
|   |-- architecture/         # Architecture boundaries and reviews
|   |-- roadmap/              # Milestones and stage planning
|   |-- adr/                  # Architecture Decision Records
|   |-- api/                  # Future interface documentation
|   |-- database/             # Future data and migration documentation
|   |-- ui/                   # Future experience and interaction documentation
|   |-- development/          # Engineering workflow and repository practices
|   |-- deployment/           # Future release and operations documentation
|   |-- meeting/              # Decision-oriented meeting records
|   `-- research/             # Time-boxed investigations
|-- AGENTS.md                 # AI Development Handbook
|-- CHANGELOG.md              # Notable project changes
|-- CONTRIBUTING.md           # Contributor workflow
|-- PROJECT_ROADMAP.md        # Long-term stage roadmap
`-- README.md                 # Project entry point
```

Checkpoint 0 establishes governance only. It intentionally contains no business application, API, database, UI, infrastructure, market-data, or AI implementation.
