"""Enforce DEV-GOV-001 per-module statement + branch coverage, not just repository average."""

import json
from pathlib import Path

from .models import GovernanceError

TARGETS = {
    "state_machine.py": 95,
    "gates.py": 100,
    "budget.py": 95,
    "store.py": 95,
    "github.py": 90,
}


def verify_coverage(path: Path) -> dict[str, float]:
    report = json.loads(path.read_text("utf-8"))
    results = {}
    for module, target in TARGETS.items():
        matches = [
            value
            for key, value in report["files"].items()
            if key.replace("\\", "/").endswith("aic_dev_governance/" + module)
        ]
        if len(matches) != 1 or not report["meta"]["branch_coverage"]:
            raise GovernanceError("COVERAGE_EVIDENCE_MISSING")
        coverage = float(matches[0]["summary"]["percent_covered"])
        if coverage < target:
            raise GovernanceError(f"COVERAGE_BELOW_TARGET:{module}")
        results[module] = coverage
    return results
