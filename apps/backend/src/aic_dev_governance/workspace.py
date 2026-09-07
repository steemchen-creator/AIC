"""Allowlisted Git operations. No shell, arbitrary command strings, checkout reset or force."""

import re
import subprocess
from pathlib import Path

from .models import GovernanceError


class GitWorkspace:
    def __init__(self, root: Path, executable: str = "git") -> None:
        self.root, self.executable = root.resolve(), executable

    def _git(self, *arguments: str) -> str:
        if not arguments or arguments[0] not in {
            "status",
            "fetch",
            "switch",
            "merge",
            "merge-base",
            "rev-parse",
            "show-ref",
            "update-ref",
        }:
            raise GovernanceError("COMMAND_NOT_ALLOWLISTED")
        try:
            result = subprocess.run(
                [self.executable, *arguments],
                cwd=self.root,
                shell=False,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (subprocess.SubprocessError, OSError) as error:
            raise GovernanceError("WORKSPACE_GIT_FAILED") from error
        return result.stdout.strip()

    def closeout(self, branch: str, head: str, merge_commit: str, main: str) -> None:
        if not re.fullmatch(r"feature/[a-z0-9][a-z0-9-]+", branch):
            raise GovernanceError("BRANCH_DELETION_NOT_ALLOWED")
        if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (head, merge_commit, main)):
            raise GovernanceError("SHA_INVALID")
        if self._git("status", "--porcelain"):
            raise GovernanceError("WORKSPACE_DIRTY")
        self._git("fetch", "origin")
        if self._git("rev-parse", "origin/main") != main:
            raise GovernanceError("REMOTE_MAIN_CHANGED")
        self._git("merge-base", "--is-ancestor", merge_commit, "origin/main")
        if self._git("rev-parse", f"{head}^{{tree}}") != self._git(
            "rev-parse",
            f"{merge_commit}^{{tree}}",
        ):
            raise GovernanceError("MERGE_TREE_REVIEW_REQUIRED")
        self._git("switch", "main")
        self._git("merge", "--ff-only", "origin/main")
        if self._git("rev-parse", "HEAD") != main:
            raise GovernanceError("LOCAL_MAIN_MISMATCH")
        refs = self._git("show-ref", "--heads")
        expected_ref = f"refs/heads/{branch}"
        local = [line.split()[0] for line in refs.splitlines() if line.split()[1] == expected_ref]
        if local:
            if local != [head]:
                raise GovernanceError("BRANCH_HAS_UNMERGED_WORK")
            # Expected-old-SHA conditional ref deletion also supports verified squash merges.
            self._git("update-ref", "-d", expected_ref, head)
        if expected_ref in self._git("show-ref", "--heads"):
            raise GovernanceError("LOCAL_BRANCH_DELETION_FAILED")
        if self._git("status", "--porcelain"):
            raise GovernanceError("WORKSPACE_DIRTY")
