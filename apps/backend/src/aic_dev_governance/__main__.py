"""python -m aic_dev_governance --help"""

import argparse
import json
import os
from pathlib import Path

import httpx
from pydantic import ValidationError

from .artifacts import dashboard
from .github import GitHubClient
from .models import GovernanceError
from .observability import metrics
from .runner import generate_review_context, run, run_bootstrap, run_policy_rotation, run_setup
from .store import GitHubStateBranchStore, LocalFileStateStore


def main() -> int:
    parser = argparse.ArgumentParser(description="AIC deterministic development control plane")
    parser.add_argument(
        "command",
        choices=[
            "gate",
            "run",
            "bootstrap",
            "setup",
            "rotate-policy",
            "status",
            "metrics",
            "context",
        ],
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--state-dir", type=Path, default=Path("tmp/dev-governance/state"))
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--output", type=Path, default=Path("tmp/REVIEW_CONTEXT.json"))
    args = parser.parse_args()
    try:
        if args.command == "context":
            token = os.environ.get("GH_TOKEN")
            number = args.pr_number or int(os.environ.get("AIC_PR_NUMBER") or "0")
            if not token or not number:
                raise GovernanceError("CONTEXT_PR_AND_AUTH_REQUIRED")
            with httpx.Client(headers={"Authorization": f"Bearer {token}"}) as client:
                github = GitHubClient(client, "steemchen-creator/AIC")
                state, _ = GitHubStateBranchStore(github).load()
                context = generate_review_context(args.root, github, number, state)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(context.model_dump_json(indent=2), encoding="utf-8")
            print(f"REVIEW_CONTEXT: {args.output}")
        elif args.command in {"status", "metrics"}:
            state, _ = LocalFileStateStore(args.state_dir).load()
            print(
                dashboard(state)
                if args.command == "status"
                else json.dumps(
                    {work_item: metrics(state, work_item) for work_item in state.work_items},
                    indent=2,
                )
            )
        elif args.command == "bootstrap":
            print(run_bootstrap(args.root))
        elif args.command == "setup":
            print(run_setup(args.root))
        elif args.command == "rotate-policy":
            print(run_policy_rotation(args.root))
        else:
            print(run(args.root, gate_only=args.command == "gate"))
    except (GovernanceError, ValidationError, ValueError, KeyError, OSError) as error:
        print(error.reason if isinstance(error, GovernanceError) else "INPUT_OR_STATE_INVALID")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
