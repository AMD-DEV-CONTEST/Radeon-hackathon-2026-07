import httpx
import pytest

from policyseal.api.app import create_app


@pytest.mark.asyncio
async def test_health_reports_local_runtime() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "policyseal-api",
        "version": "0.1.0",
        "environment": "development",
        "inference": "local",
    }
