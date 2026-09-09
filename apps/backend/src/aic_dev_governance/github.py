"""Owned GitHub REST boundary: bounded reads, no blind mutation retries, no force."""

import base64
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

from .models import CI, Check, GovernanceError, Policy, PullRequest, WorkflowRun
from .observability import log_operation


class GitHubClient:
    def __init__(
        self,
        client: httpx.Client,
        repository: str,
        *,
        attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise GovernanceError("REPOSITORY_INVALID")
        if not 1 <= attempts <= 5:
            raise GovernanceError("RETRY_POLICY_INVALID")
        self.client, self.repository, self.attempts, self.sleep = (
            client,
            repository,
            attempts,
            sleep,
        )
        self._protection_observed = False

    def request(self, method: str, path: str, data: dict[str, Any] | None = None) -> Any:
        if method not in {"GET", "POST", "PATCH", "PUT", "DELETE"} or not path.startswith("/"):
            raise GovernanceError("HTTP_OPERATION_NOT_ALLOWED")
        attempts = self.attempts if method == "GET" else 1
        for attempt in range(attempts):
            started = time.monotonic()
            try:
                response = self.client.request(
                    method,
                    f"https://api.github.com/repos/{self.repository}{path}",
                    json=data,
                    timeout=20.0,
                )
            except httpx.TransportError as error:
                log_operation("repository", method, "TRANSPORT_FAILURE", started, retry=attempt)
                if attempt + 1 == attempts:
                    raise GovernanceError("GITHUB_UNAVAILABLE") from error
            else:
                log_operation(
                    "repository", method, str(response.status_code), started, retry=attempt
                )
                if response.status_code < 300:
                    if response.status_code == 204:
                        return None
                    try:
                        return response.json()
                    except ValueError as error:
                        raise GovernanceError("GITHUB_RESPONSE_INVALID") from error
                if response.status_code not in {429, 500, 502, 503, 504} or attempt + 1 == attempts:
                    raise GovernanceError(f"GITHUB_HTTP_{response.status_code}")
            self.sleep(float(2**attempt))
        raise GovernanceError("GITHUB_UNAVAILABLE")  # defensive, attempts validated above

    def pages(self, path: str, key: str | None = None) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        separator = "&" if "?" in path else "?"
        for page in range(1, 51):
            data = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            values = data[key] if key else data
            if not isinstance(values, list):
                raise GovernanceError("GITHUB_RESPONSE_INVALID")
            output.extend(values)
            if len(values) < 100:
                return output
        raise GovernanceError("GITHUB_PAGINATION_LIMIT")

    def pull_request(self, number: int) -> PullRequest:
        raw = self.request("GET", f"/pulls/{number}")
        return PullRequest(
            number=raw["number"],
            head_sha=raw["head"]["sha"],
            base_sha=raw["base"]["sha"],
            branch=raw["head"]["ref"],
            state="MERGED" if raw["merged"] else raw["state"].upper(),
            draft=raw["draft"],
            head_repository=raw["head"]["repo"]["full_name"],
            base_branch=raw["base"]["ref"],
            merge_commit=raw["merge_commit_sha"] if raw["merged"] else None,
        )

    def changed_paths(self, number: int) -> list[str]:
        files = self.pages(f"/pulls/{number}/files")
        # Fail closed at the PR-files API ceiling instead of certifying a partial diff.
        if len(files) >= 3000:
            raise GovernanceError("GITHUB_DIFF_INCOMPLETE")
        paths = {str(value["filename"]) for value in files}
        paths.update(
            str(value["previous_filename"]) for value in files if "previous_filename" in value
        )
        return sorted(paths)

    def required_checks(self, policy: Policy) -> dict[str, int | None]:
        required: dict[str, int | None] = {
            name: policy.trusted_check_app_id for name in policy.required_checks
        }
        # Effective rules cover repository/org rulesets; inability to discover fails closed.
        rules = self.request("GET", "/rules/branches/main")
        for rule in rules:
            if rule["type"] == "required_status_checks":
                for check in rule["parameters"]["required_status_checks"]:
                    required[check["context"]] = check.get("integration_id")
        branch = self.request("GET", "/branches/main")
        self._protection_observed = bool(branch["protected"])
        if branch["protected"]:
            protection = self.request("GET", "/branches/main/protection/required_status_checks")
            for name in protection.get("contexts", []):
                required.setdefault(name, None)
            for check in protection.get("checks", []):
                required[check["context"]] = check.get("app_id")
        return required

    def ci(self, pr: PullRequest, policy: Policy) -> CI:
        required = self.required_checks(policy)
        raw = self.pages(f"/commits/{pr.head_sha}/check-runs?filter=latest", "check_runs")
        checks = []
        workflows: dict[int, WorkflowRun] = {}
        for check in raw:
            run_id = check["id"]
            app_id = check["app"]["id"]
            expected_app = required.get(check["name"])
            relevant_action = (
                check["name"] in required
                and app_id == (expected_app or policy.trusted_check_app_id)
                and app_id == policy.trusted_check_app_id
            )
            if relevant_action:
                match = re.search(r"/actions/runs/(\d+)(?:/|$)", check["html_url"])
                if not match:
                    raise GovernanceError("CI_WORKFLOW_ID_MISSING")
                run_id = int(match.group(1))
                if run_id not in workflows:
                    run = self.request("GET", f"/actions/runs/{run_id}")
                    workflows[run_id] = WorkflowRun(
                        run_id=run["id"],
                        head_sha=run["head_sha"],
                        status=run["status"],
                        conclusion=run["conclusion"],
                        attempt=run["run_attempt"],
                        url=run["html_url"],
                    )
            # GitHub returns the latest check per name/app. Never accept a check from another SHA.
            checks.append(
                Check(
                    name=check["name"],
                    head_sha=check["head_sha"],
                    conclusion=check["conclusion"] or "pending",
                    run_id=run_id,
                    app_id=app_id,
                    url=check["html_url"],
                )
            )
        relevant = [
            check
            for check in checks
            if check.name in required
            and check.app_id == (required[check.name] or policy.trusted_check_app_id)
        ]
        passed = set(c.name for c in relevant) == set(required) and all(
            c.conclusion == "success" and c.head_sha == pr.head_sha for c in relevant
        )
        passed = passed and all(
            run.head_sha == pr.head_sha
            and run.status == "completed"
            and run.conclusion == "success"
            for run in workflows.values()
        )
        failed = any(c.conclusion not in {"success", "pending"} for c in relevant) or any(
            run.status == "completed" and run.conclusion not in {"success", None}
            for run in workflows.values()
        )
        return CI(
            head_sha=pr.head_sha,
            status="PASSED" if passed else "FAILED" if failed else "PENDING",
            required_checks=required,
            checks=checks,
            discovery_complete=True,
            workflow_runs=list(workflows.values()),
            branch_protection_enabled=self._protection_observed,
        )

    def ref(self, branch: str) -> str | None:
        try:
            return str(
                self.request("GET", f"/git/ref/heads/{quote(branch, safe='/')}")["object"]["sha"]
            )
        except GovernanceError as error:
            if error.reason == "GITHUB_HTTP_404":
                return None
            raise

    def tree(self, commit: str) -> str:
        return str(self.request("GET", f"/git/commits/{commit}")["tree"]["sha"])

    def contains_commit(self, ancestor: str, descendant: str) -> bool:
        comparison = self.request("GET", f"/compare/{ancestor}...{descendant}")
        return comparison.get("status") in {"ahead", "identical"}

    def file(self, path: str, ref: str) -> str:
        raw = self.request("GET", f"/contents/{quote(path, safe='/')}?ref={quote(ref, safe='')}")
        if raw.get("encoding") != "base64" or raw.get("type") != "file":
            raise GovernanceError("ARTIFACT_ENCODING_INVALID")
        return base64.b64decode(raw["content"]).decode("utf-8")

    def merge(self, number: int, expected_head_sha: str) -> str:
        result = self.request(
            "PUT",
            f"/pulls/{number}/merge",
            {
                "sha": expected_head_sha,
                "merge_method": "squash",
            },
        )
        if not result.get("merged"):
            raise GovernanceError("MERGE_PERMISSION_DENIED")
        return str(result["sha"])

    def mark_ready(self, number: int, expected_head_sha: str) -> None:
        self._change_draft(number, expected_head_sha, "markPullRequestReadyForReview")

    def mark_draft(self, number: int, expected_head_sha: str) -> None:
        self._change_draft(number, expected_head_sha, "convertPullRequestToDraft")

    def _change_draft(self, number: int, expected_head_sha: str, operation: str) -> None:
        raw = self.request("GET", f"/pulls/{number}")
        if raw["head"]["sha"] != expected_head_sha:
            raise GovernanceError("PR_HEAD_CHANGED")
        try:
            response = self.client.post(
                "https://api.github.com/graphql",
                timeout=20.0,
                json={
                    "query": "mutation($id:ID!){"
                    + operation
                    + "(input:{pullRequestId:$id}){pullRequest{isDraft}}}",
                    "variables": {"id": raw["node_id"]},
                },
            )
        except httpx.TransportError as error:
            raise GovernanceError("GITHUB_UNAVAILABLE") from error
        if response.status_code != 200 or response.json().get("errors"):
            raise GovernanceError("PR_READY_FAILED")
        if self.pull_request(number).head_sha != expected_head_sha:
            raise GovernanceError("PR_HEAD_CHANGED")

    def delete_branch(self, branch: str, expected_sha: str) -> None:
        if not re.fullmatch(r"feature/[a-z0-9][a-z0-9-]+", branch):
            raise GovernanceError("BRANCH_DELETION_NOT_ALLOWED")
        actual = self.ref(branch)
        if actual is None:
            return
        if actual != expected_sha:
            raise GovernanceError("BRANCH_HAS_UNMERGED_WORK")
        self.request("DELETE", f"/git/refs/heads/{branch}")
        if self.ref(branch) is not None:
            raise GovernanceError("BRANCH_DELETION_FAILED")

    def publish_task(self, task_id: str, body: str, pr_number: int | None) -> str:
        marker = f"<!-- aic-task:{task_id} -->"
        if pr_number:
            path = f"/issues/{pr_number}/comments"
            for comment in self.pages(path):
                if marker in comment["body"]:
                    # This is only transport deduplication, never authority/approval.
                    return str(comment["html_url"])
            return str(self.request("POST", path, {"body": marker + "\n" + body})["html_url"])
        for issue in self.pages("/issues?state=all&creator=@me"):
            if marker in (issue.get("body") or ""):
                return str(issue["html_url"])
        return str(
            self.request(
                "POST",
                "/issues",
                {
                    "title": f"AIC task {task_id}",
                    "body": marker + "\n" + body,
                },
            )["html_url"]
        )
