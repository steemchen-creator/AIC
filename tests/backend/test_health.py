from httpx import ASGITransport, AsyncClient

from apps.backend.app.main import app


async def test_root() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"project": "AIC", "status": "running"}


async def test_health() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    assert {route.path for route in app.routes} == {"/", "/health"}
