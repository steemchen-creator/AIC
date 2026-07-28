import ast
from pathlib import Path


PACKAGE_ROOT = Path("apps/backend/src/aic_backend")


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def package_imports(package: str) -> set[str]:
    imports: set[str] = set()
    for path in (PACKAGE_ROOT / package).rglob("*.py"):
        imports.update(imported_modules(path))
    return imports


def test_domain_uses_standard_library_only() -> None:
    allowed_roots = {"dataclasses", "datetime", "types", "typing"}
    external_imports = {
        module
        for module in package_imports("domain")
        if not module.startswith("aic_backend.domain")
    }

    assert {module.split(".")[0] for module in external_imports} <= allowed_roots


def test_application_does_not_depend_on_outer_layers() -> None:
    forbidden = (
        "aic_backend.bootstrap",
        "aic_backend.infrastructure",
        "aic_backend.presentation",
        "aic_backend.providers",
        "fastapi",
        "pydantic",
        "sqlalchemy",
        "redis",
        "celery",
    )

    assert not {
        module
        for module in package_imports("application")
        if module.startswith(forbidden)
    }


def test_presentation_does_not_depend_on_concrete_adapters() -> None:
    forbidden = (
        "aic_backend.bootstrap",
        "aic_backend.infrastructure",
        "aic_backend.providers",
    )

    assert not {
        module
        for module in package_imports("presentation")
        if module.startswith(forbidden)
    }
