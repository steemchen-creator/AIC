"""One-time protected deployment setup and reproducible effective-policy materialization."""

import hashlib
import json

from .models import DeploymentPolicyConfig, GovernanceError, Policy, Role, State


def policy_fingerprint(config: DeploymentPolicyConfig) -> str:
    canonical = json.dumps(
        config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_deployment_policy(config: DeploymentPolicyConfig, actor: str) -> None:
    principals = config.principals
    if set(principals) != set(Role) or any(
        not values or any(not value.strip() for value in values) or len(values) != len(set(values))
        for values in principals.values()
    ):
        raise GovernanceError("DEPLOYMENT_PRINCIPALS_INVALID")
    if actor not in principals[Role.CHAIRMAN] or any(
        actor in principals[role] for role in (Role.ARCHITECT, Role.ENGINEER, Role.BOT)
    ):
        raise GovernanceError("DEPLOYMENT_CHAIRMAN_IDENTITY_INVALID")
    role_sets = {role: set(values) for role, values in principals.items()}
    roles = list(Role)
    for index, role in enumerate(roles):
        if any(role_sets[role].intersection(role_sets[other]) for other in roles[index + 1 :]):
            raise GovernanceError("DEPLOYMENT_ROLE_SEPARATION_INVALID")
    if "github-actions[bot]" not in principals[Role.BOT]:
        raise GovernanceError("DEPLOYMENT_ORCHESTRATOR_IDENTITY_MISSING")
    if config.mode == "DRY_RUN" and config.merge_enabled:
        raise GovernanceError("DRY_RUN_MERGE_FORBIDDEN")
    if config.bridge_mode == "OPENAI_API_BRIDGE" and config.bridge_authorized:
        if not config.openai_model:
            raise GovernanceError("AUTHORIZED_API_MODEL_REQUIRED")
    elif config.openai_model is not None:
        raise GovernanceError("OPENAI_MODEL_WITHOUT_API_BRIDGE")
    if config.bridge_mode == "MANUAL_BRIDGE" and config.bridge_authorized:
        raise GovernanceError("MANUAL_BRIDGE_AUTHORIZATION_INVALID")


def _without_principals(config: DeploymentPolicyConfig) -> dict[str, object]:
    values = config.model_dump(mode="json")
    values.pop("principals")
    return values


def validate_policy_rotation(
    current: DeploymentPolicyConfig,
    proposed: DeploymentPolicyConfig,
    actor: str,
) -> None:
    """Validate Chairman authority and the V1 principals-only change boundary."""
    if actor not in current.principals[Role.CHAIRMAN] or any(
        actor in current.principals[role] for role in (Role.ARCHITECT, Role.ENGINEER, Role.BOT)
    ):
        raise GovernanceError("DEPLOYMENT_POLICY_ROTATION_CHAIRMAN_NOT_AUTHORIZED")
    validate_deployment_policy(proposed, actor)
    if _without_principals(current) != _without_principals(proposed):
        raise GovernanceError("DEPLOYMENT_POLICY_ROTATION_NON_PRINCIPAL_CHANGE")
    if current.principals == proposed.principals:
        raise GovernanceError("DEPLOYMENT_POLICY_ROTATION_NO_CHANGE")


def resolve_deployment_policy(
    state: State,
) -> tuple[DeploymentPolicyConfig, str] | None:
    """Validate and resolve the setup plus every append-only rotation link."""
    setup = state.deployment_setup
    if setup is None:
        if state.deployment_policy_rotations:
            raise GovernanceError("DEPLOYMENT_POLICY_ROTATION_WITHOUT_SETUP")
        return None
    fingerprint = policy_fingerprint(setup.effective_policy)
    if setup.policy_fingerprint != fingerprint:
        raise GovernanceError("DEPLOYMENT_POLICY_FINGERPRINT_MISMATCH")
    config = setup.effective_policy
    validate_deployment_policy(config, setup.authorized_by)
    for rotation in state.deployment_policy_rotations:
        if rotation.previous_policy_fingerprint != fingerprint:
            raise GovernanceError("DEPLOYMENT_POLICY_ROTATION_CHAIN_MISMATCH")
        proposed_fingerprint = policy_fingerprint(rotation.new_effective_policy)
        if rotation.new_policy_fingerprint != proposed_fingerprint:
            raise GovernanceError("DEPLOYMENT_POLICY_ROTATION_FINGERPRINT_MISMATCH")
        validate_policy_rotation(config, rotation.new_effective_policy, rotation.authorized_by)
        config = rotation.new_effective_policy
        fingerprint = proposed_fingerprint
    return config.model_copy(deep=True), fingerprint


def materialize_effective_policy(static: Policy, state: State, *, activated: bool) -> Policy:
    """Rebuild effective policy from immutable state; the repo activation flag is a kill switch."""
    if any(
        (
            static.pipeline_enabled,
            static.merge_enabled,
            static.auto_ready,
            static.bridge_authorized,
            static.mode != "MANUAL",
            static.bridge_mode != "MANUAL_BRIDGE",
            static.openai_model is not None,
            static.standard_work_execution_authorization is not None,
            any(
                static.principals.get(role, [])
                for role in (Role.CHAIRMAN, Role.ARCHITECT, Role.ENGINEER)
            ),
        )
    ):
        raise GovernanceError("MUTABLE_DEPLOYMENT_POLICY_FORBIDDEN")
    resolved = resolve_deployment_policy(state)
    if resolved is None:
        if activated:
            raise GovernanceError("DEPLOYMENT_SETUP_REQUIRED")
        return static.model_copy(deep=True)
    config, _ = resolved
    effective = static.model_copy(deep=True)
    effective.pipeline_enabled = activated and config.pipeline_enabled
    effective.mode = config.mode
    effective.merge_enabled = activated and config.merge_enabled
    effective.auto_ready = False
    effective.bridge_mode = config.bridge_mode
    effective.bridge_authorized = activated and config.bridge_authorized
    effective.openai_model = config.openai_model
    effective.standard_work_execution_authorization = config.standard_work_execution_authorization
    effective.principals = {role: list(values) for role, values in config.principals.items()}
    return effective
