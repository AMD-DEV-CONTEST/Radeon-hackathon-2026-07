import asyncio

import httpx

from app.config import Settings
from app.llm.health import check_model_health, model_health_url
from app.main import create_app


def test_health_url_uses_llama_server_endpoint() -> None:
    settings = Settings(_env_file=None)

    assert model_health_url(settings) == "http://127.0.0.1:8000/health"


def test_model_unreachable_is_reported() -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = asyncio.run(
        check_model_health(Settings(_env_file=None), transport=httpx.MockTransport(fail))
    )

    assert result.reachable is False
    assert "unavailable" in result.detail


def test_api_health_reports_reachable_model() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok"})

    async def request_health() -> httpx.Response:
        app = create_app(
            Settings(_env_file=None),
            model_health_transport=httpx.MockTransport(respond),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["model_service"]["reachable"] is True
