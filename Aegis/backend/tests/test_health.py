import pytest


@pytest.mark.asyncio
async def test_health_returns_component_statuses(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["app_name"] == "Aegis"
    names = {c["name"] for c in body["components"]}
    assert names == {"database", "redis", "inference_engine"}
