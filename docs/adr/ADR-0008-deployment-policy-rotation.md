# ADR-0008: Append-only deployment-policy principal rotation

- Status: Proposed — implementation authorized by DEV-GOV-RECOVERY-001; Architecture Review pending.
- Date: 2026-09-09
- Authority: Chairman-requested governance recovery, not self-approval by its implementer.

## Context and decision

The one-time DEV-GOV-001 Deployment Setup correctly makes its effective policy immutable.
That safety property also means a lost or unavailable GitHub principal cannot be recovered by
editing checked-in configuration or rerunning setup. The current `aic-architect` account is
unavailable, while `aic-architect-2` has been provisioned as its operational replacement.

Retain Deployment Setup as the immutable chain root and add a list of immutable policy-rotation
records to state. Each record contains both adjacent fingerprints, the complete new non-secret
policy, authorizing Chairman, aware timestamp and reason. The state-store append check protects
the prefix, while every materialization validates the root and all links before using the last
policy. V1 permits only changes to principals and continues to apply all existing policy and
role-separation validation.

Expose the transition only through a dedicated protected manual workflow. It runs trusted
`main`, uses the existing setup environment, requires the external pipeline variable to be
exactly OFF, authenticates the current Chairman, and writes only through the existing CAS state
store. It does not invoke autonomous orchestration, Ready or merge behavior.

## Alternatives

- Edit `deployment_setup`: rejected because it destroys the approved chain root and violates
  the store's explicit no-rewrite invariant.
- Rerun one-time setup: rejected because duplicate setup is prohibited and would obscure which
  policy authorized earlier actions.
- Change checked-in static principals: rejected because repository policy is deliberately
  safe/off and ordinary PR content is not a privileged identity source.
- Manually edit `automation/dev-state`: rejected because it bypasses authentication, canonical
  fingerprinting, CAS and append-only audit enforcement.
- Remove the unavailable identity immediately: rejected for this recovery because retaining it
  while adding the new principal preserves continuity and is sufficient to restore operations.

## Impact and risks

Old state remains schema-compatible because the rotation list defaults empty. Each accepted
rotation adds one state entry, one audit event and one immutable state-branch artifact. Runtime
policy resolution does additional deterministic validation proportional to the short rotation
history. No investment code, product database, business interface, merge gate or CI trust rule
changes.

A compromised current Chairman or protected environment could authorize a malicious principal;
repository administration therefore remains a trust root. Stale fingerprints, role overlap,
secret-like content and any V1 non-principal change fail closed. A workflow run can still face
ordinary network or CAS failure; operators must re-read the chain tip before retrying.

## Rollout and rollback

Review and merge this implementation through normal branch protection. With the pipeline OFF,
the Chairman may run the protected workflow using the documented full policy that adds
`aic-architect-2`. Independently verify the resulting chain and keep automatic Ready and merge
disabled.

Rollback is forward-only: append another reviewed, Chairman-authorized rotation restoring the
prior principal set. Never force-update the state branch, delete a rotation, change the original
setup, or use this path to alter mode, bridge, delegation, Ready or merge behavior.
