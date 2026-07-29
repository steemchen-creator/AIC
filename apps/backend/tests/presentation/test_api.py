from httpx import ASGITransport, AsyncClient

from aic_backend.bootstrap import build_container
from aic_backend.presentation import create_app
from aic_backend.shared import Environment, Settings


def make_testing_app():
    return create_app(
        get_data_record=build_container().get_data_record,
        settings=Settings(environment=Environment.TESTING),
    )


async def test_existing_foundation_endpoints_remain_compatible() -> None:
    app = make_testing_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        root = await client.get("/")
        health = await client.get("/health")

    assert root.status_code == 200
    assert root.json() == {"project": "AIC", "status": "running"}
    assert health.status_code == 200
    assert health.json() == {"status": "healthy"}


async def test_health_is_a_liveness_response_without_runtime_dependency_probe() -> None:
    calls = 0

    async def startup_check(_: Settings) -> None:
        nonlocal calls
        calls += 1

    app = create_app(
        get_data_record=build_container().get_data_record,
        settings=Settings(environment=Environment.TESTING, verify_dependencies=False),
        startup_check=startup_check,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.json() == {"status": "healthy"}
    assert calls == 0


async def test_data_endpoint_returns_mock_record() -> None:
    app = make_testing_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/data/sample-1")

    assert response.status_code == 200
    assert response.json() == {
        "record_id": "sample-1",
        "source": "mock",
        "payload": {"value": 42},
        "observed_at": "2026-01-01T00:00:00Z",
    }


async def test_data_endpoint_returns_stable_not_found_response() -> None:
    app = make_testing_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/data/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Data record not found"}
    assert {route.path for route in app.routes} == {"/", "/health", "/data/{record_id}"}
