import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src"


def imports(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_investment_code_never_imports_development_control_plane():
    for path in (ROOT / "aic_backend").rglob("*.py"):
        assert not any(name.startswith("aic_dev_governance") for name in imports(path))


def test_development_control_plane_never_imports_investment_code():
    for path in (ROOT / "aic_dev_governance").glob("*.py"):
        assert not any(
            name.startswith(("aic_backend", "sqlalchemy", "fastapi", "celery"))
            for name in imports(path)
        )


def test_deterministic_gates_and_state_machine_have_no_model_network_or_shell():
    for module in ("gates.py", "state_machine.py", "budget.py"):
        assert not imports(ROOT / "aic_dev_governance" / module).intersection(
            {
                "httpx",
                "openai",
                "subprocess",
                "github",
                "bridges",
                "runner",
                "store",
            }
        )


def test_privileged_workflow_uses_main_and_no_pr_code_or_script_interpolation():
    repository = ROOT.parents[2]
    workflow = (repository / ".github/workflows/dev-governance.yml").read_text("utf-8")
    assert "ref: main" in workflow and "persist-credentials: false" in workflow
    assert "github.event.pull_request.head" not in workflow
    assert "cancel-in-progress: false" in workflow
    assert "environment: aic-development-governance" in workflow
