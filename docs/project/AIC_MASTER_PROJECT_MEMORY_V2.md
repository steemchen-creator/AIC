# AIC Master Project Memory V2

## Authority and scope

Repository memory, not a new Master Requirement. Canonical governing requirements are
[AGENTS.md](../../AGENTS.md), the owner-approved current SPEC and accepted ADRs.
[PROJECT_ROADMAP.md](../../PROJECT_ROADMAP.md) remains the single roadmap source.
Do not invent investment requirements from this summary or conversational history.

## Project and roles

AIC is an institution-grade intelligent financial terminal. Correctness, auditability,
security and maintainability precede speed. Chairman controls capital, major policy,
permissions and exceptions; Chief Investment Architect owns architecture approval;
Codex/CTO implements and produces evidence; deterministic governance enforces gates.
Execution authorization is not architecture approval or Chairman policy approval.

## Verified baseline and current development state

SPEC-003 through SPEC-009 foundations are present; see README and their review artifacts.
SPEC-009 PR #10 premature merge was a GOVERNANCE_PROCESS_DEVIATION, not retroactively
made compliant by tree equality. Exception publication PR #11 was manually merged at
`2026-09-06T17:23:54Z`, merge `1b9e3d50921751a9b016fcf4bb82a9d813a2bdd7`.
Corrected governance tree: `4437e9e4c13be2c899120c3bf63c3cc1add2f6dc`.
The owner explicitly relayed Chief Investment Architect Post-Publication Closeout:
`FINAL APPROVED WITH NON-BLOCKING DEBT / GOVERNANCE EXCEPTION RECORDED /
PROCESS DEVIATION OCCURRED / FORMAL CLOSEOUT COMPLETE`.
The historical [exception record](../governance/SPEC009_PREMATURE_MERGE_EXCEPTION.md)
retains its pre-publication snapshot; this memory does not rewrite that evidence.

DEV-GOV-001 is the currently authorized engineering task. Its bootstrap requires owner
manual merge after Architecture Review. SPEC-010 is NOT STARTED. No future SPEC is
authorized by merely mentioning its number in examples or by completing a model call.
Live development state, once activated, belongs in `automation/dev-state/state/current.json`.

## Recovery reading order

Read this memory, AGENTS, roadmap, [architecture](AIC_ARCHITECTURE.md),
[technical debt](TECHNICAL_DEBT.md), relevant ADRs, current approved SPEC/FIX, immutable
state, exact PR HEAD and CI. Missing or contradictory sources block progression.
Review manifests carry content hashes; changed memory is not silently inherited.

## Memory update gate

Major architecture, new asset class, Chairman policy, governance incident, role change,
master requirement or roadmap change requires an audited memory-update reminder.
An ordinary bugfix does not justify rewriting the master project direction.
