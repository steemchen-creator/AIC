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
    allowed_roots = {
        "collections",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "types",
        "typing",
        "urllib",
    }
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


def test_real_data_foundation_phase_1_has_no_outer_or_future_dependencies() -> None:
    forbidden = (
        "aic_backend.bootstrap",
        "aic_backend.infrastructure",
        "aic_backend.presentation",
        "aic_backend.provider_runtime",
        "fastapi",
        "pydantic",
        "sqlalchemy",
        "redis",
        "celery",
    )
    data_imports = package_imports("data_foundation")
    market_domain_imports = package_imports("domain/market_data")

    assert not {module for module in data_imports if module.startswith(forbidden)}
    assert not {module for module in market_domain_imports if module.startswith(forbidden)}

    phase_1_paths = (
        PACKAGE_ROOT / "data_foundation/canonical.py",
        PACKAGE_ROOT / "data_foundation/identity.py",
        *(PACKAGE_ROOT / "domain/market_data").rglob("*.py"),
    )
    phase_1_source = "\n".join(
        path.read_text(encoding="utf-8") for path in phase_1_paths
    ).casefold()
    forbidden_concepts = (
        "fastapi",
        "httpx",
        "requests",
        "sqlalchemy",
        "asyncpg",
        "validationengine",
        "qualityengine",
        "canonicaldatarepository",
    )
    assert not {concept for concept in forbidden_concepts if concept in phase_1_source}


def test_validation_engine_is_pure_and_has_no_phase_3_or_adapter_dependencies() -> None:
    validation_root = PACKAGE_ROOT / "data_foundation/validation"
    imports: set[str] = set()
    source_parts: list[str] = []
    for path in validation_root.rglob("*.py"):
        imports.update(imported_modules(path))
        source_parts.append(path.read_text(encoding="utf-8"))

    forbidden_imports = (
        "aic_backend.bootstrap",
        "aic_backend.infrastructure",
        "aic_backend.presentation",
        "aic_backend.provider_runtime",
        "aic_backend.providers",
        "asyncpg",
        "fastapi",
        "httpx",
        "pydantic",
        "redis",
        "requests",
        "sqlalchemy",
        "urllib.request",
    )
    assert not {module for module in imports if module.startswith(forbidden_imports)}

    source = "\n".join(source_parts).casefold()
    forbidden_operations = (
        "qualityengine",
        "qualityscore",
        "canonicaldatarepository",
        "open(",
        "socket.",
        "urlopen(",
    )
    assert not {operation for operation in forbidden_operations if operation in source}


def test_data_quality_engine_is_pure_and_separate_from_provider_runtime_score() -> None:
    quality_root = PACKAGE_ROOT / "data_foundation/quality"
    imports: set[str] = set()
    source_parts: list[str] = []
    for path in quality_root.rglob("*.py"):
        imports.update(imported_modules(path))
        source_parts.append(path.read_text(encoding="utf-8"))

    forbidden_imports = (
        "aic_backend.bootstrap",
        "aic_backend.infrastructure",
        "aic_backend.presentation",
        "aic_backend.provider_runtime",
        "aic_backend.providers",
        "asyncpg",
        "fastapi",
        "httpx",
        "redis",
        "requests",
        "sqlalchemy",
        "urllib.request",
    )
    assert not {module for module in imports if module.startswith(forbidden_imports)}

    source = "\n".join(source_parts).casefold()
    forbidden_operations = (
        "providerselector",
        "qualityscorer",
        "normalizationpipeline",
        "ingestionpipeline",
        "canonicaldatarepository",
        "open(",
        "socket.",
        "urlopen(",
    )
    assert not {operation for operation in forbidden_operations if operation in source}


def test_normalization_and_ingestion_keep_phase_4_boundaries() -> None:
    phase_4_paths = (
        PACKAGE_ROOT / "data_foundation/normalization.py",
        PACKAGE_ROOT / "data_foundation/ingestion.py",
    )
    imports: set[str] = set()
    for path in phase_4_paths:
        imports.update(imported_modules(path))

    forbidden_imports = (
        "aic_backend.bootstrap",
        "aic_backend.infrastructure",
        "aic_backend.presentation",
        "aic_backend.provider_runtime",
        "aic_backend.providers",
        "asyncpg",
        "fastapi",
        "httpx",
        "redis",
        "requests",
        "sqlalchemy",
        "urllib.request",
    )
    assert not {module for module in imports if module.startswith(forbidden_imports)}

    ingestion_imports = imported_modules(phase_4_paths[1])
    assert "aic_backend.data_foundation.validation" in ingestion_imports
    assert "aic_backend.data_foundation.quality" in ingestion_imports

    source = "\n".join(
        path.read_text(encoding="utf-8") for path in phase_4_paths
    ).casefold()
    forbidden_operations = (
        "open(",
        "socket.",
        "urlopen(",
        "providerselector",
        "lifecyclemanager",
        "healthmanager",
        "failovermanager",
        "canonicaldatarepository",
        "freshness_weight",
        "source_weight",
        "daily_bar_high_invalid",
        "daily_bar_low_invalid",
    )
    assert not {operation for operation in forbidden_operations if operation in source}


def test_fixture_raw_field_names_do_not_leak_into_market_domain_models() -> None:
    model_source = (PACKAGE_ROOT / "domain/market_data/models.py").read_text(
        encoding="utf-8"
    )
    model_tree = ast.parse(model_source)
    declared_fields = {
        node.target.id
        for node in ast.walk(model_tree)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }

    assert not declared_fields.intersection(
        {"ticker", "trade_day", "o", "h", "l", "c", "vol", "amount"}
    )


def test_phase_5_persistence_technology_stays_in_infrastructure() -> None:
    pure_packages = (
        "domain/market_data",
        "data_foundation/validation",
        "data_foundation/quality",
    )
    pure_files = (
        PACKAGE_ROOT / "data_foundation/normalization.py",
        PACKAGE_ROOT / "data_foundation/ingestion.py",
    )
    forbidden = ("alembic", "asyncpg", "psycopg", "sqlalchemy")

    for package in pure_packages:
        assert not {
            module
            for module in package_imports(package)
            if module.startswith(forbidden)
        }
    for path in pure_files:
        assert not {
            module for module in imported_modules(path) if module.startswith(forbidden)
        }

    adapter = PACKAGE_ROOT / "infrastructure/canonical_persistence.py"
    adapter_imports = imported_modules(adapter)
    assert "aic_backend.application.ports.persistence" in adapter_imports
    assert any(module.startswith("sqlalchemy") for module in adapter_imports)
    assert not {
        module
        for module in adapter_imports
        if module.startswith(("aic_backend.presentation", "aic_backend.provider_runtime"))
    }


def test_phase_5_does_not_add_future_or_provider_behavior() -> None:
    paths = (
        PACKAGE_ROOT / "application/ports/persistence.py",
        PACKAGE_ROOT / "application/use_cases/persist_ingestion.py",
        PACKAGE_ROOT / "infrastructure/canonical_persistence.py",
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths).casefold()
    forbidden = (
        "providerselector",
        "retryengine",
        "reconciliation",
        "investmentstrategy",
        "fastapi",
        "redis",
        "requests",
        "httpx",
    )
    assert not {item for item in forbidden if item in source}


def test_phase_6_tushare_dependencies_stay_at_owned_boundaries() -> None:
    adapter = PACKAGE_ROOT / "providers/tushare.py"
    normalizer = PACKAGE_ROOT / "data_foundation/tushare_normalization.py"
    persistence = PACKAGE_ROOT / "infrastructure/canonical_persistence.py"
    runtime_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PACKAGE_ROOT / "provider_runtime").rglob("*.py")
    ).casefold()

    assert "httpx" in imported_modules(adapter)
    assert not {
        module
        for module in imported_modules(adapter)
        if module.startswith(("sqlalchemy", "aic_backend.infrastructure"))
    }
    assert not {
        module
        for module in imported_modules(normalizer)
        if module.startswith(("httpx", "requests", "sqlalchemy", "urllib.request"))
    }
    assert "tushare" not in "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PACKAGE_ROOT / "application").rglob("*.py")
    ).casefold()
    assert "tushare" not in persistence.read_text(encoding="utf-8").casefold()
    assert "tushare" not in runtime_source


def test_phase_7_historical_service_keeps_application_and_adapter_boundaries() -> None:
    application_paths = (
        PACKAGE_ROOT / "application/ports/historical.py",
        PACKAGE_ROOT / "application/use_cases/historical_daily_bars.py",
        PACKAGE_ROOT / "application/use_cases/backfill_daily_bars.py",
    )
    application_imports: set[str] = set()
    for path in application_paths:
        application_imports.update(imported_modules(path))
    forbidden = (
        "aic_backend.bootstrap",
        "aic_backend.infrastructure",
        "aic_backend.presentation",
        "aic_backend.providers",
        "httpx",
        "requests",
        "sqlalchemy",
    )
    assert not {
        module for module in application_imports if module.startswith(forbidden)
    }
    backfill_imports = imported_modules(application_paths[2])
    assert "aic_backend.application.use_cases.ingest_daily_bars" in backfill_imports
    assert "aic_backend.provider_runtime" in backfill_imports

    adapter_imports = imported_modules(
        PACKAGE_ROOT / "infrastructure/historical_persistence.py"
    )
    assert "aic_backend.application.ports.historical" in adapter_imports
    assert any(module.startswith("sqlalchemy") for module in adapter_imports)

    provider_imports = imported_modules(PACKAGE_ROOT / "providers/tushare.py")
    assert not {
        module
        for module in provider_imports
        if module.startswith(("sqlalchemy", "aic_backend.infrastructure"))
    }
    source = "\n".join(path.read_text(encoding="utf-8") for path in application_paths)
    assert not {
        concept
        for concept in (
            "aic_backend.strategy",
            "aic_backend.portfolio",
            "aic_backend.trading",
            "aic_backend.presentation",
            "aic_backend.providers.tushare",
        )
        if concept in source.casefold()
    }


def test_only_lifecycle_manager_writes_provider_runtime_state() -> None:
    callers = {
        path.name
        for path in (PACKAGE_ROOT / "provider_runtime").glob("*.py")
        if path.name != "registry.py"
        and "_replace_runtime_state" in path.read_text(encoding="utf-8")
    }

    assert callers == {"lifecycle.py"}


def test_selection_and_scoring_keep_pure_runtime_boundaries() -> None:
    runtime_root = PACKAGE_ROOT / "provider_runtime"
    selector_imports = imported_modules(runtime_root / "selector.py")
    scoring_imports = imported_modules(runtime_root / "scoring.py")
    forbidden = (
        "aic_backend.bootstrap",
        "aic_backend.presentation",
        "aic_backend.providers",
        "fastapi",
    )

    assert not {module for module in selector_imports if module.startswith(forbidden)}
    assert "aic_backend.provider_runtime.registry" not in selector_imports
    assert "aic_backend.provider_runtime.registry" not in scoring_imports
    assert "aic_backend.provider_runtime.interfaces" not in scoring_imports
    assert "datetime.datetime.now" not in (runtime_root / "scoring.py").read_text(
        encoding="utf-8"
    )
    for name in ("registry.py", "lifecycle.py", "health.py"):
        assert "provider_runtime.selector" not in imported_modules(runtime_root / name)
    assert not {
        module
        for module in package_imports("application")
        if module.startswith("aic_backend.provider_runtime.selector")
    }


def test_invocation_keeps_runtime_execution_boundaries() -> None:
    runtime_root = PACKAGE_ROOT / "provider_runtime"
    imports = imported_modules(runtime_root / "invocation.py")
    forbidden = (
        "aic_backend.bootstrap",
        "aic_backend.lifecycle",
        "aic_backend.presentation",
        "aic_backend.providers",
        "fastapi",
    )

    assert not {module for module in imports if module.startswith(forbidden)}
    assert "aic_backend.provider_runtime.lifecycle" not in imports
    assert "aic_backend.provider_runtime.invocation" not in imported_modules(
        runtime_root / "selector.py"
    )


def test_failover_reuses_selector_without_crossing_runtime_boundaries() -> None:
    runtime_root = PACKAGE_ROOT / "provider_runtime"
    imports = imported_modules(runtime_root / "failover.py")
    forbidden = (
        "aic_backend.bootstrap",
        "aic_backend.infrastructure",
        "aic_backend.presentation",
        "aic_backend.providers",
        "aic_backend.provider_runtime.health",
        "aic_backend.provider_runtime.lifecycle",
        "aic_backend.provider_runtime.registry",
        "fastapi",
        "redis",
        "sqlalchemy",
    )

    assert "aic_backend.provider_runtime.selector" in imports
    assert not {module for module in imports if module.startswith(forbidden)}


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
