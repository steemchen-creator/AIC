# DEV-GOV-001 Chairman Setup

No setup or investment authorization is inferred from implementation completion.

## Before activation

- [ ] Receive Chief Investment Architect final approval of exact DEV-GOV-001 HEAD.
- [ ] Manually merge its PR, complete formal Closeout and delete its feature branch.
- [ ] Ask the repository administrator to apply the branch-protection checklist.
- [ ] Choose MANUAL or DRY_RUN first. Auto Merge remains NO unless separately authorized.
- [ ] Assign distinct engineering, architecture and Chairman identities.
- [ ] Approve the protected main-only governance environment and least-privilege bot token.
- [ ] Choose a Chairman escalation recipient/channel.

## Optional external bridge

- [ ] Work mode: authorize the GitHub event/task consumer and repository read access.
- [ ] API mode: approve a specific model and budget; add OPENAI_API_KEY as a protected secret.
- [ ] Confirm the separate API architecture principal; never reuse the engineering identity.
- [ ] Have the maintainer apply the chosen values in a reviewed trusted-main configuration.
- [ ] Enable AIC_PIPELINE_ENABLED only after the protected setup has been verified.

## One-time state initialization

The maintainer prepares the protected workflow initialize payload with the manually
merged DEV-GOV PR number and your external Architecture Closeout reference. Confirm
that run after branch cleanup. The code checks actual merge/tree/main/CI, imports the
closed bootstrap and creates only automation/dev-state. No code writing is required
from the Chairman, and initialization does not start SPEC-010.

## Emergency

Turn AIC_PIPELINE_ENABLED off; revoke the dedicated token when necessary.
No force-merge bypass is offered. Preserve state/audit for recovery.

Current delivery: all activation switches OFF; no live AI calls, no bot merge and
no SPEC-010 work. Setup is a separate post-review decision.
