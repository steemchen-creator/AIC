"""Atomic state + append-only audit. Product branches are never a state backend."""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Protocol

from .github import GitHubClient
from .models import GovernanceError, State


class StateStore(Protocol):
    def load(self) -> tuple[State, str | None]: ...

    def save(self, state: State, expected_revision: str | None) -> str: ...


def validate_append(previous: State, current: State) -> None:
    if current.revision <= previous.revision:
        raise GovernanceError("STATE_REVISION_NOT_ADVANCED")
    if current.events[: len(previous.events)] != previous.events:
        raise GovernanceError("AUDIT_REWRITE_PROHIBITED")
    if len(current.events) <= len(previous.events):
        raise GovernanceError("AUDIT_EVENT_REQUIRED")
    for key, value in previous.reviews.items():
        if current.reviews.get(key) != value:
            raise GovernanceError("REVIEW_REWRITE_PROHIBITED")
    for key, artifact_content in previous.artifacts.items():
        if current.artifacts.get(key) != artifact_content:
            raise GovernanceError("ARTIFACT_REWRITE_PROHIBITED")
    if (
        previous.deployment_setup is not None
        and current.deployment_setup != previous.deployment_setup
    ):
        raise GovernanceError("DEPLOYMENT_SETUP_REWRITE_PROHIBITED")


class LocalFileStateStore:
    """One atomic envelope includes current state and all events; suitable for tests/local runs."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "current.json"

    def load(self) -> tuple[State, str | None]:
        if not self.path.exists():
            return State(), None
        raw = self.path.read_bytes()
        return State.model_validate_json(raw), hashlib.sha256(raw).hexdigest()

    def save(self, state: State, expected_revision: str | None) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = self.directory / ".write.lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise GovernanceError("STATE_CONFLICT") from error
        temporary: str | None = None
        try:
            os.close(descriptor)
            previous, revision = self.load()
            if revision != expected_revision:
                raise GovernanceError("STATE_CONFLICT")
            validate_append(previous, state)
            payload = state.model_dump_json(indent=2).encode("utf-8")
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as handle:
                temporary = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
            return hashlib.sha256(payload).hexdigest()
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
            lock.unlink()


class GitHubStateBranchStore:
    """Non-force ref update of a sibling commit is rejected by GitHub: optimistic CAS."""

    branch = "automation/dev-state"

    def __init__(self, github: GitHubClient) -> None:
        self.github = github

    def load(self) -> tuple[State, str | None]:
        revision = self.github.ref(self.branch)
        if revision is None:
            return State(), None
        return State.model_validate_json(self.github.file("state/current.json", revision)), revision

    def save(self, state: State, expected_revision: str | None) -> str:
        previous, actual = self.load()
        if actual != expected_revision:
            raise GovernanceError("STATE_BRANCH_CONFLICT")
        validate_append(previous, state)
        files = {"state/current.json": state.model_dump_json(indent=2)}
        for event in state.events[len(previous.events) :]:
            files[f"state/events/{event.event_id}.json"] = event.model_dump_json(indent=2)
        for key, review in state.reviews.items():
            if key not in previous.reviews:
                root = f"architecture/reviews/{review.work_item}/{key}"
                files[f"{root}.json"] = review.model_dump_json(indent=2)
                files[f"{root}.md"] = (
                    f"# {review.work_item}: {review.result}\n\n"
                    f"Reviewed HEAD: `{review.reviewed_head_sha}`\n\n"
                    f"```json\n{review.model_dump_json(indent=2)}\n```\n"
                )
        files.update(
            {key: value for key, value in state.artifacts.items() if key not in previous.artifacts}
        )
        tree_data: dict[str, object] = {
            "tree": [
                {"path": path, "mode": "100644", "type": "blob", "content": content}
                for path, content in files.items()
            ]
        }
        if actual:
            tree_data["base_tree"] = self.github.tree(actual)
        tree = self.github.request("POST", "/git/trees", tree_data)["sha"]
        commit = self.github.request(
            "POST",
            "/git/commits",
            {
                "message": f"chore(dev-state): record revision {state.revision}",
                "tree": tree,
                "parents": [actual] if actual else [],
            },
        )["sha"]
        try:
            if actual:
                self.github.request(
                    "PATCH",
                    f"/git/refs/heads/{self.branch}",
                    {
                        "sha": commit,
                        "force": False,
                    },
                )
            else:
                self.github.request(
                    "POST",
                    "/git/refs",
                    {
                        "ref": f"refs/heads/{self.branch}",
                        "sha": commit,
                    },
                )
        except GovernanceError as error:
            if error.reason in {"GITHUB_HTTP_409", "GITHUB_HTTP_422"}:
                raise GovernanceError("STATE_BRANCH_CONFLICT") from error
            # An ambiguous network failure is not retried; re-read state before any new action.
            raise
        return str(commit)
