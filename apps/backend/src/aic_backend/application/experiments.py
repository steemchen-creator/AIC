"""Application orchestration for fair Champion and Shadow portfolio experiments."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import cast

from aic_backend.application.ports.experiments import (
    ExperimentClock,
    ExperimentDecisionSource,
    ExperimentPaperRuntime,
    ShadowExperimentRecord,
    ShadowExperimentRepository,
)
from aic_backend.domain.experiments import (
    ComparisonPolicy,
    ExperimentManifest,
    ExperimentMember,
    ExperimentMemberDefinition,
    ExperimentPolicyBundle,
    FairnessContract,
    GroupSessionStatus,
    GroupTradingSession,
    ManagerProfile,
    MemberSessionResult,
    MemberSessionStatus,
    PortfolioRole,
    RoleActivity,
    RoleActivityStatus,
    RoleActivityView,
    RoleAvatarReferenceUpdated,
    build_comparison_snapshot,
    build_role_activity_board,
    current_manager_profile,
    latest_role_activity,
    stable_experiment_id,
)
from aic_backend.domain.paper import ActivatePaperAccount, PaperRuntimeError


@dataclass(frozen=True, slots=True)
class CreateShadowExperiment:
    group_id: str
    display_name: str
    policy_bundle: ExperimentPolicyBundle
    members: tuple[ExperimentMemberDefinition, ...]


@dataclass(frozen=True, slots=True)
class UpdateRoleAvatarReference:
    group_id: str
    manager_id: str
    avatar_reference: str


class ShadowExperimentService:
    """Coordinates accounts while keeping every portfolio state independent."""

    def __init__(
        self,
        paper_runtime: ExperimentPaperRuntime,
        repository: ShadowExperimentRepository,
        clock: ExperimentClock,
        comparison_policy: ComparisonPolicy | None = None,
    ) -> None:
        self._paper_runtime = paper_runtime
        self._repository = repository
        self._clock = clock
        self._comparison_policy = comparison_policy or ComparisonPolicy()

    async def create(self, command: CreateShadowExperiment) -> ExperimentManifest:
        existing = await self._repository.get(command.group_id)
        if existing is not None:
            expected_definitions = self._sorted_definitions(command.members)
            existing_definitions = tuple(
                item.definition for item in existing.manifest.members
            )
            if (
                existing.manifest.display_name != command.display_name.strip()
                or existing.manifest.policy_bundle != command.policy_bundle
                or existing_definitions != expected_definitions
            ):
                raise ValueError("group_id identifies a different experiment definition")
            return existing.manifest
        if not command.group_id.strip() or not command.display_name.strip():
            raise ValueError("group_id and display_name must not be empty")
        self._validate_definitions(command.members)
        now = self._clock.now()
        definitions = self._sorted_definitions(command.members)
        members: list[ExperimentMember] = []
        for definition in definitions:
            reference = f"{command.group_id}:{definition.profile.role_identity.value}"
            account = await self._paper_runtime.create_account(
                f"{command.display_name} / {definition.profile.display_name}",
                command.policy_bundle.initial_capital,
                account_reference=reference,
            )
            await self._paper_runtime.activate(ActivatePaperAccount(account.account_id, now))
            members.append(
                ExperimentMember(
                    account.account_id,
                    account.portfolio_id,
                    definition,
                    command.policy_bundle.identity,
                    account.initial_capital,
                )
            )
        member_values = tuple(members)
        contract = FairnessContract(
            stable_experiment_id(
                "fairness-contract", command.group_id, command.policy_bundle.identity
            ),
            command.policy_bundle.identity,
            command.policy_bundle.initial_capital,
            tuple(item.account_id for item in member_values),
            tuple(sorted(FairnessContract.REQUIRED_DIMENSIONS)),
            now,
        )
        manifest = ExperimentManifest(
            command.group_id,
            command.display_name,
            command.policy_bundle,
            member_values,
            contract,
            now,
        )
        activities = tuple(
            self._activity(manifest, member, None, RoleActivityStatus.READY, now)
            for member in manifest.members
        )
        await self._repository.save(ShadowExperimentRecord(manifest, activities=activities))
        return manifest

    async def run_session(
        self,
        group_id: str,
        trading_date: date,
        decision_sources: Mapping[str, ExperimentDecisionSource],
    ) -> GroupTradingSession:
        record = await self._required_record(group_id)
        existing = next(
            (item for item in record.sessions if item.trading_date == trading_date), None
        )
        if existing is not None:
            return existing
        started_at = self._clock.now()
        session_id = stable_experiment_id("group-session", group_id, trading_date)
        results: list[MemberSessionResult] = []
        performance = []
        activities = list(record.activities)
        for member in record.manifest.members:
            activities.append(
                self._activity(
                    record.manifest,
                    member,
                    session_id,
                    RoleActivityStatus.PROCESSING,
                    started_at,
                    task_reference=session_id,
                )
            )
            assignment = member.definition.decision_source
            source = decision_sources.get(assignment.source_id)
            source_error = None
            if source is None:
                source_error = "DECISION_SOURCE_UNAVAILABLE"
            elif (
                source.source_id != assignment.source_id
                or getattr(source, "version", None) != assignment.version
            ):
                source_error = "DECISION_SOURCE_CONTRACT_MISMATCH"
            if source_error is not None:
                results.append(
                    MemberSessionResult(
                        member.account_id,
                        assignment.source_id,
                        MemberSessionStatus.FAILED,
                        None,
                        None,
                        source_error,
                    )
                )
                activities.append(
                    self._activity(
                        record.manifest,
                        member,
                        session_id,
                        RoleActivityStatus.ERROR,
                        self._clock.now(),
                        source_error,
                        task_reference=session_id,
                    )
                )
                continue
            source = cast(ExperimentDecisionSource, source)
            try:
                result = await self._paper_runtime.process_session(
                    member.account_id, trading_date, source
                )
            except Exception as error:  # member isolation is an explicit runtime boundary
                code = (
                    error.code.value
                    if isinstance(error, PaperRuntimeError)
                    else type(error).__name__
                )
                results.append(
                    MemberSessionResult(
                        member.account_id,
                        assignment.source_id,
                        MemberSessionStatus.FAILED,
                        None,
                        None,
                        code,
                    )
                )
                activities.append(
                    self._activity(
                        record.manifest,
                        member,
                        session_id,
                        RoleActivityStatus.ERROR,
                        self._clock.now(),
                        code,
                        task_reference=session_id,
                    )
                )
                continue
            if result is None:
                results.append(
                    MemberSessionResult(
                        member.account_id,
                        assignment.source_id,
                        MemberSessionStatus.SKIPPED,
                        None,
                        None,
                    )
                )
                activity_status = RoleActivityStatus.WAITING
                task_reference = session_id
                output_reference = None
            else:
                results.append(
                    MemberSessionResult(
                        member.account_id,
                        assignment.source_id,
                        MemberSessionStatus.SUCCEEDED,
                        result.session.session_id,
                        result.performance.snapshot_id,
                    )
                )
                performance.append(result.performance)
                activity_status = RoleActivityStatus.READY
                task_reference = None
                output_reference = result.performance.snapshot_id
            activities.append(
                self._activity(
                    record.manifest,
                    member,
                    session_id,
                    activity_status,
                    self._clock.now(),
                    task_reference=task_reference,
                    output_reference=output_reference,
                )
            )
        finalized_at = self._clock.now()
        failed = any(item.status is MemberSessionStatus.FAILED for item in results)
        skipped = all(item.status is MemberSessionStatus.SKIPPED for item in results)
        group_status = (
            GroupSessionStatus.SKIPPED
            if skipped
            else (
                GroupSessionStatus.FINALIZED_WITH_FAILURES
                if failed
                else GroupSessionStatus.FINALIZED
            )
        )
        session = GroupTradingSession(
            session_id,
            group_id,
            trading_date,
            started_at,
            started_at,
            finalized_at,
            group_status,
            tuple(results),
            record.manifest.policy_bundle.identity,
        )
        comparisons = record.comparisons
        if performance:
            history_counts = {
                member.account_id: 1
                + sum(
                    metric.account_id == member.account_id
                    for comparison in record.comparisons
                    for metric in comparison.metrics
                )
                for member in record.manifest.members
            }
            comparisons += (
                build_comparison_snapshot(
                    record.manifest,
                    session,
                    tuple(performance),
                    history_counts,
                    self._comparison_policy,
                ),
            )
        await self._repository.save(
            replace(
                record,
                sessions=record.sessions + (session,),
                comparisons=comparisons,
                activities=tuple(activities),
            )
        )
        return session

    async def get(self, group_id: str) -> ShadowExperimentRecord | None:
        return await self._repository.get(group_id)

    async def role_activity(self, group_id: str) -> tuple[RoleActivity, ...]:
        record = await self._required_record(group_id)
        return latest_role_activity(record.activities)

    async def role_activity_board(self, group_id: str) -> tuple[RoleActivityView, ...]:
        record = await self._required_record(group_id)
        return build_role_activity_board(
            record.manifest,
            record.activities,
            record.profile_events,
        )

    async def role_profiles(self, group_id: str) -> tuple[ManagerProfile, ...]:
        record = await self._required_record(group_id)
        return tuple(
            current_manager_profile(member, record.profile_events)
            for member in record.manifest.members
        )

    async def update_role_avatar_reference(
        self, command: UpdateRoleAvatarReference
    ) -> ManagerProfile:
        if not command.group_id.strip() or not command.manager_id.strip():
            raise ValueError("group_id and manager_id must not be empty")
        record = await self._required_record(command.group_id)
        member = next(
            (
                item
                for item in record.manifest.members
                if item.definition.profile.manager_id == command.manager_id.strip()
            ),
            None,
        )
        if member is None:
            raise LookupError(f"manager not found in shadow experiment: {command.manager_id}")
        current = current_manager_profile(member, record.profile_events)
        normalized_reference = command.avatar_reference.strip()
        if current.avatar_reference == normalized_reference:
            return current
        occurred_at = self._clock.now()
        event = RoleAvatarReferenceUpdated(
            stable_experiment_id(
                "avatar-update",
                record.manifest.group_id,
                member.account_id,
                len(record.profile_events) + 1,
            ),
            record.manifest.group_id,
            member.account_id,
            current.manager_id,
            current.avatar_reference,
            normalized_reference,
            occurred_at,
        )
        await self._repository.save(
            replace(record, profile_events=record.profile_events + (event,))
        )
        return replace(current, avatar_reference=event.new_avatar_reference)

    async def _required_record(self, group_id: str) -> ShadowExperimentRecord:
        record = await self._repository.get(group_id)
        if record is None:
            raise LookupError(f"shadow experiment not found: {group_id}")
        return record

    @staticmethod
    def _sorted_definitions(
        definitions: tuple[ExperimentMemberDefinition, ...],
    ) -> tuple[ExperimentMemberDefinition, ...]:
        return tuple(
            sorted(
                definitions,
                key=lambda item: (
                    item.portfolio_role is not PortfolioRole.CHAMPION,
                    item.profile.role_identity.value,
                ),
            )
        )

    @staticmethod
    def _validate_definitions(
        definitions: tuple[ExperimentMemberDefinition, ...],
    ) -> None:
        champion_count = sum(
            item.portfolio_role is PortfolioRole.CHAMPION for item in definitions
        )
        shadow_count = sum(
            item.portfolio_role is PortfolioRole.SHADOW for item in definitions
        )
        if champion_count != 1 or shadow_count < 3:
            raise ValueError("experiment requires exactly one Champion and at least three Shadows")
        for field_name, values in (
            ("manager_id", tuple(item.profile.manager_id for item in definitions)),
            ("role_identity", tuple(item.profile.role_identity for item in definitions)),
            ("source_id", tuple(item.decision_source.source_id for item in definitions)),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"experiment definition {field_name} values must be unique")

    @staticmethod
    def _activity(
        manifest: ExperimentManifest,
        member: ExperimentMember,
        group_session_id: str | None,
        status: RoleActivityStatus,
        occurred_at: datetime,
        reason_code: str | None = None,
        *,
        task_reference: str | None = None,
        output_reference: str | None = None,
    ) -> RoleActivity:
        return RoleActivity(
            stable_experiment_id(
                "role-activity",
                manifest.group_id,
                member.account_id,
                group_session_id or "CREATED",
                status.value,
            ),
            manifest.group_id,
            group_session_id,
            member.account_id,
            member.definition.profile.manager_id,
            occurred_at,
            status,
            reason_code,
            task_reference,
            output_reference,
        )
