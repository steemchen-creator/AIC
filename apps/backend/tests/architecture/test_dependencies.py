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
    allowed_roots = {"collections", "dataclasses", "datetime", "types", "typing"}
    external_imports = {
        module
        for module in package_imports("domain")
        if not module.startswith("aic_backend.domain")
    }

    assert {module.split(".")[0] for module in external_imports} <= allowed_roots

    assert not {
        module
        for module in package_imports("domain")
        if module.startswith("aic_backend.application")
    }

    assert not {
        module
        for module in package_imports("domain")
        if module.startswith("aic_backend.provider_runtime")
    }


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


def test_providers_do_not_depend_on_presentation() -> None:
    assert not {
        module
        for module in package_imports("providers")
        if module.startswith("aic_backend.presentation")
    }


def test_infrastructure_does_not_depend_on_presentation() -> None:
    assert not {
        module
        for module in package_imports("infrastructure")
        if module.startswith("aic_backend.presentation")
    }


def test_provider_runtime_does_not_depend_on_outer_layers() -> None:
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
        for module in package_imports("provider_runtime")
        if module.startswith(forbidden)
    }


def test_only_lifecycle_manager_writes_provider_runtime_state() -> None:
    callers = {
        path.name
        for path in (PACKAGE_ROOT / "provider_runtime").glob("*.py")
        if path.name != "registry.py"
        and "_replace_runtime_state" in path.read_text(encoding="utf-8")
    }

    assert callers == {"lifecycle.py"}


def test_only_bootstrap_combines_application_and_concrete_adapters() -> None:
    concrete_roots = ("aic_backend.infrastructure", "aic_backend.providers")
    layer_packages = (
        "application",
        "domain",
        "presentation",
        "provider_runtime",
        "shared",
    )

    for package in layer_packages:
        imports = package_imports(package)
        references_application = any(
            module.startswith("aic_backend.application") for module in imports
        )
        references_concrete = any(
            module.startswith(concrete_roots) for module in imports
        )
        assert not (references_application and references_concrete), package

    bootstrap_imports = package_imports("bootstrap")
    assert any(
        module.startswith("aic_backend.application") for module in bootstrap_imports
    )
    assert any(module.startswith(concrete_roots) for module in bootstrap_imports)
