# DEV-GOV-001 Chairman Setup

No setup, execution authorization, Architecture Approval, or investment authorization
is inferred from implementation completion. This procedure is post-merge only.

## Exact deployment sequence

1. Receive Chief Investment Architect Final Approval for the exact DEV-GOV-001 HEAD.
2. Human-merge PR #12, complete formal Closeout, and delete its feature branch.
3. Create protected environment `aic-development-governance-bootstrap`, require the
   designated reviewer, and set `AIC_BOOTSTRAP_CHAIRMAN` to the authorized GitHub login.
4. Run `AIC Development Governance Bootstrap` once with `pr_number`, exact
   `reviewed_head_sha`, and `architecture_closeout_reference`. This creates
   `automation/dev-state` with only closed DEV-GOV-001 evidence; it does not activate
   the normal pipeline or create SPEC-010.
5. Apply the main branch-protection checklist: required PR reviews, no bypass or direct
   push, and all required exact-HEAD checks including `AIC Development Governance Gate`.
6. Create protected environment `aic-development-governance-setup`, require the
   designated Chairman/admin reviewer, and set the two environment variables described
   below. Keep repository variable `AIC_PIPELINE_ENABLED=false`; do not shadow that switch
   with an environment variable of the same name.
7. Run `AIC Development Governance Setup` once. Verify its summary and the immutable
   `DEPLOYMENT_SETUP_COMPLETED` state event, policy version, SHA-256 fingerprint,
   principals, MANUAL/DRY_RUN mode, bridge mode, merge/Ready flags, actor, and timestamp.
8. Verify an ordinary registered fixture PR passes the Governance Gate using durable
   WorkItem identity. Do not edit `.github/dev-governance/work-item.json`; it is
   bootstrap-only.
9. Set repository variable `AIC_PIPELINE_ENABLED=true`. This external kill switch makes
   the already-recorded MANUAL or DRY_RUN policy usable. It cannot create or alter policy
   and must remain false until step 8 succeeds.
10. Have the authorized Architect register the first approved ordinary work item. The
    registered SPEC moves to `SPEC_READY`, after which the approved engineering consumer
    may receive its bounded task.
11. Connect an external ChatGPT Work/Codex consumer only after its identity and access are
    separately approved. For API mode, authorize a model and budget and install
    `OPENAI_API_KEY` only as a protected secret; never place a token in policy JSON/state.
12. Consider AUTO/Auto Merge only in a separate, reviewed Chairman-governed change.
    This V1 setup schema permits only MANUAL or DRY_RUN and fixes `auto_ready=false`.

The order does not need a bypass: bootstrap is a distinct post-merge import, branch
protection is applied before deployment setup, setup runs from trusted `main` under a
protected environment while the normal pipeline is off, and later PRs already have a
state-based registration path.

## Protected deployment settings

In environment `aic-development-governance-setup`, configure:

- `AIC_SETUP_CHAIRMAN`: the exact authorized GitHub actor. It must be in Chairman
  principals and in no Architect, Engineer, or bot role.
- `AIC_DEPLOYMENT_POLICY`: non-secret JSON matching this shape. Use real reviewed logins
  and an explicit delegation reference; do not copy placeholder identities to production.

```json
{
  "policy_version": "DEPLOYMENT-V1",
  "pipeline_enabled": true,
  "mode": "MANUAL",
  "merge_enabled": false,
  "auto_ready": false,
  "bridge_mode": "CHATGPT_WORK_EVENT_BRIDGE",
  "bridge_authorized": false,
  "openai_model": null,
  "standard_work_execution_authorization": "CHAIRMAN-DELEGATION-REFERENCE",
  "principals": {
    "CHAIRMAN": ["authorized-chairman-login"],
    "CHIEF_INVESTMENT_ARCHITECT": ["authorized-architect-login"],
    "CTO": ["authorized-engineer-login"],
    "ORCHESTRATOR": ["github-actions[bot]"]
  }
}
```

`pipeline_enabled=true` inside this record describes the deployable policy. It has no
effect until the separate repository kill switch becomes true. DRY_RUN must keep merge
disabled. Role lists must be explicit, non-empty, unique, and separated. Setup validates
the schema and secret-like content, stores the complete non-secret policy plus its
fingerprint, and fails closed on duplicate or changed setup.

## What is automatic and one-time

- Bootstrap and deployment setup are separate, protected, manual, one-time workflows.
- Bootstrap proves reviewed merge/closeout/current-main containment/exact CI/branch
  deletion before creating the state branch.
- Deployment setup requires closed bootstrap state and the normal pipeline still OFF.
- Normal activation only re-materializes the immutable fingerprinted policy from state;
  mutable repository config cannot supply privileged identities/delegation.
- Later workflow/config changes are ordinary sensitive PRs and trigger Chairman/Governance
  controls. The one-time authority is not reusable.

## Emergency and recovery

Set `AIC_PIPELINE_ENABLED=false` first, then revoke the dedicated token or bridge secret
if necessary. Preserve `automation/dev-state`, the setup event, protected-environment
review evidence, and workflow run. Recovery must reproduce the stored policy and verify
its fingerprint; do not edit state, bypass checks, or force-merge.

Current PR delivery remains inactive: Pipeline OFF, Auto Merge OFF,
`automation/dev-state` not initialized, and SPEC-010 not started.
