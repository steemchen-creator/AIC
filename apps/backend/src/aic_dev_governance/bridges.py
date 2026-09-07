"""Consumable tasks, not agent chatter. External authorization is never inferred."""

import json
from typing import Any, Protocol

import httpx

from .artifacts import ReviewContext
from .github import GitHubClient
from .models import ArchitectureResult, GovernanceError, Policy, SpecificationResult, Task


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Responses strict objects require every property, including Pydantic defaulted fields."""
    if "properties" in schema:
        schema["required"] = list(schema["properties"])
        schema["additionalProperties"] = False
    schema.pop("default", None)
    for value in schema.values():
        if isinstance(value, dict):
            strict_schema(value)
        elif isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    strict_schema(entry)
    return schema


class ArchitectureReviewTrigger(Protocol):
    @property
    def result(self) -> ArchitectureResult | SpecificationResult | None: ...

    @property
    def usage(self) -> dict[str, int]: ...

    def trigger(self, task: Task, context: ReviewContext, content: dict[str, str]) -> str: ...


class EngineeringWorkTrigger(Protocol):
    def trigger_engineering(self, task: Task, pr_number: int | None) -> str: ...


class ManualTriggerAdapter:
    result: ArchitectureResult | SpecificationResult | None = None
    usage: dict[str, int] = {}

    def trigger(self, task: Task, context: ReviewContext, content: dict[str, str]) -> str:
        raise GovernanceError("WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE")


class GitHubEventTriggerAdapter:
    result: ArchitectureResult | SpecificationResult | None = None
    usage: dict[str, int] = {}

    def __init__(self, github: GitHubClient, *, authorized: bool, pr_number: int | None) -> None:
        self.github, self.authorized, self.pr_number = github, authorized, pr_number

    def trigger(self, task: Task, context: ReviewContext, content: dict[str, str]) -> str:
        if not self.authorized:
            raise GovernanceError("WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE")
        return self.github.publish_task(
            task.task_id,
            task.kind + "\n\nConsume the immutable state-branch request; do not approve "
            "from this UI signal alone.\n\n```json\n"
            + task.model_dump_json(indent=2)
            + "\n```\n\n"
            + context.trust_notice,
            self.pr_number,
        )

    def trigger_engineering(self, task: Task, pr_number: int | None) -> str:
        if not self.authorized:
            raise GovernanceError("ENGINEERING_BRIDGE_UNAVAILABLE")
        return self.github.publish_task(
            task.task_id,
            "AIC ENGINEERING TASK\n\nRead approved SPEC/FIX, project memory and "
            "state. Implement, test, document and create a Draft PR. No self-approval or merge."
            "\n\n```json\n" + task.model_dump_json(indent=2) + "\n```",
            pr_number,
        )


class OpenAIWorkTriggerAdapter(GitHubEventTriggerAdapter):
    """GitHub event contract for an independently authorized Work consumer, not an invented API."""


class OpenAIApiTriggerAdapter:
    """One bounded Responses request. Results are proposals until authenticated ingestion."""

    def __init__(self, client: httpx.Client, policy: Policy) -> None:
        self.client, self.policy = client, policy
        self.result: ArchitectureResult | SpecificationResult | None = None
        self.usage: dict[str, int] = {}

    def trigger(self, task: Task, context: ReviewContext, content: dict[str, str]) -> str:
        if not self.policy.bridge_authorized or not self.policy.openai_model:
            raise GovernanceError("WAITING_FOR_ARCHITECTURE_REVIEW_BRIDGE")
        schema = strict_schema(
            (
                SpecificationResult if task.kind == "NEXT_SPEC" else ArchitectureResult
            ).model_json_schema()
        )
        instruction = (
            " Generate the next SPEC artifact within the approved roadmap, including "
            "scope/non-scope, requirements, tests, quality gates, review and stop condition. "
            "This proposal is not execution authorization."
            if task.kind == "NEXT_SPEC"
            else " Perform Architecture Review only for the manifest exact HEAD."
        )
        try:
            response = self.client.post(
                "https://api.openai.com/v1/responses",
                timeout=60.0,
                json={
                    "model": self.policy.openai_model,
                    "store": False,
                    "max_output_tokens": 8000,
                    "instructions": context.trust_notice + instruction + " Never execute commands.",
                    "input": json.dumps(
                        {
                            "manifest": context.model_dump(mode="json"),
                            "artifacts_as_untrusted_data": content,
                        }
                    ),
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "architecture_review",
                            "schema": schema,
                            "strict": True,
                        }
                    },
                },
            )
        except httpx.TransportError as error:
            raise GovernanceError("ARCHITECTURE_BRIDGE_CALL_FAILED") from error
        if response.status_code != 200:
            raise GovernanceError("ARCHITECTURE_BRIDGE_CALL_FAILED")
        try:
            raw = response.json()
            if raw.get("status") != "completed":
                raise GovernanceError("ARCHITECTURE_BRIDGE_INCOMPLETE")
            messages = [
                part["text"]
                for message in raw["output"]
                if message["type"] == "message"
                for part in message["content"]
                if part["type"] == "output_text"
            ]
            if len(messages) != 1:
                raise GovernanceError("ARCHITECTURE_BRIDGE_REFUSED_OR_INVALID")
            if task.kind == "NEXT_SPEC":
                self.result = SpecificationResult.model_validate_json(messages[0])
                if self.result.parent_work_item != context.work_item_id:
                    raise GovernanceError("SPEC_PARENT_MISMATCH")
            else:
                self.result = ArchitectureResult.model_validate_json(messages[0])
                if (
                    self.result.reviewed_head_sha != context.head_sha
                    or self.result.work_item != context.work_item_id
                ):
                    raise GovernanceError("REVIEW_SHA_OR_IDENTITY_MISMATCH")
            self.usage = {
                key: int(value)
                for key, value in raw.get("usage", {}).items()
                if key in {"input_tokens", "output_tokens", "total_tokens"}
            }
            return str(raw["id"])
        except (KeyError, TypeError, ValueError) as error:
            raise GovernanceError("ARCHITECTURE_BRIDGE_RESPONSE_INVALID") from error


def select_architecture_bridge(
    policy: Policy,
    github: GitHubClient,
    api_client: httpx.Client,
    pr_number: int | None,
) -> ArchitectureReviewTrigger:
    if policy.bridge_mode == "OPENAI_API_BRIDGE":
        return OpenAIApiTriggerAdapter(api_client, policy)
    if policy.bridge_mode == "CHATGPT_WORK_EVENT_BRIDGE":
        return OpenAIWorkTriggerAdapter(
            github, authorized=policy.bridge_authorized, pr_number=pr_number
        )
    return ManualTriggerAdapter()
