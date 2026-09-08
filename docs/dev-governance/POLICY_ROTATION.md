# DEV-GOV deployment-policy rotation

## Purpose and boundary

`DEV-GOV-RECOVERY-001` provides a protected, Chairman-authorized recovery path for
deployment principals after the one-time Deployment Setup has completed. It does not rerun
setup, activate the pipeline, change workflows from a feature branch, or rewrite any event or
state history.

V1 rotation may change only the `principals` member of the complete non-secret
`DeploymentPolicyConfig`. Policy version, mode, bridge, execution authorization, merge and
Ready behavior must remain byte-equivalent after canonical model serialization. All role sets
must remain populated, duplicate-free and mutually disjoint, and `github-actions[bot]` must
remain an Orchestrator.

## Durable record

The immutable `deployment_setup` remains the chain root. Each accepted
`deployment_policy_rotations` entry records:

- the exact previous and new canonical SHA-256 fingerprints;
- the authorizing Chairman and aware UTC timestamp;
- the non-empty recovery reason; and
- the complete new non-secret deployment policy.

The state store accepts only an append whose prior rotation list is unchanged. GitHub state
persistence also writes each new entry to
`state/deployment-policy-rotations/<sequence>-<fingerprint>.json` and emits a
`DEPLOYMENT_POLICY_ROTATED` event. Runtime policy materialization validates the original setup
and every rotation link before selecting the final policy. Missing, stale, malformed, rewritten
or unauthorized links fail closed.

## Required administrative controls

Before running a rotation:

1. Merge the reviewed implementation through the normal protected `main` process.
2. Confirm repository variable `AIC_PIPELINE_ENABLED` is exactly `false`.
3. Keep the existing protected environment `aic-development-governance-setup` and its
   `AIC_SETUP_CHAIRMAN=steemchen-creator` identity control. Do not recreate Deployment Setup.
4. Read `deployment_setup.policy_fingerprint` when no rotations exist, otherwise read the last
   rotation's `new_policy_fingerprint`, from `automation/dev-state`.
5. Independently review the full proposed policy and ensure it contains no secret.
6. From the Actions page, select `AIC Development Governance Policy Rotation`, use `main`, and
   supply the current fingerprint, reason and complete policy JSON.

The workflow checks out `main` explicitly without persisted credentials. Its entry point
requires `workflow_dispatch`, `refs/heads/main`, an exact external OFF value, and a GitHub actor
equal to the protected Chairman identity. It never calls the autonomous `run` entry point.

## Authorized recovery payload

For the current Architect identity recovery, the expected chain root is:

```text
6df86a26a6681f13612536912cca2d97d1d8afe20a1138cade66fa3d7d741045
```

The complete proposed policy is:

```json
{
  "policy_version": "DEPLOYMENT-V1",
  "pipeline_enabled": true,
  "mode": "DRY_RUN",
  "merge_enabled": false,
  "auto_ready": false,
  "bridge_mode": "CHATGPT_WORK_EVENT_BRIDGE",
  "bridge_authorized": true,
  "openai_model": null,
  "standard_work_execution_authorization": "CHAIRMAN-DELEGATION-AIC-STANDARD-WORK-V1",
  "principals": {
    "CHAIRMAN": ["steemchen-creator"],
    "CHIEF_INVESTMENT_ARCHITECT": [
      "aic-architect",
      "aic-architect-2",
      "openai-architecture-bridge"
    ],
    "CTO": ["aic-codex-cto"],
    "ORCHESTRATOR": ["github-actions[bot]"]
  }
}
```

Its canonical fingerprint is:

```text
cd6f53c56de55919a15453928bff30187a1ab481400ac5a07d6e0ffe2445233f
```

Use a reason that identifies the unavailable account and the reviewed recovery authority.
The old `aic-architect` identity remains listed for record continuity; the new
`aic-architect-2` identity is added as an additional Architect principal.

## Verification and rollback

After the protected run, confirm the workflow succeeded and the state revision advanced once.
Verify the original setup is unchanged, the new rotation file and event exist, the recorded
fingerprints match the independently calculated values, and materialization recognizes all
three Architect principals. Keep the pipeline OFF until separate authorization enables it.

If validation fails, do not edit state or retry with a guessed fingerprint. Correct the input
or governance implementation through another reviewed PR. If an accepted rotation later needs
reversal, append a new Chairman-authorized principals-only rotation whose previous fingerprint
is the current chain tip; never delete or rewrite the earlier entry.
