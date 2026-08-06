from pathlib import Path

from backend.config import Settings
from backend.main import create_app


def test_settings_defaults_use_fake_backend_and_persistence_root():
    settings = Settings()
    assert settings.command_backend == "fake"
    assert settings.persistence_root == Path("/workspace/persistent/silent-vision")
    assert settings.mouth_size == 96
    assert settings.capture_fps == 25
    assert settings.capture_countdown_seconds == 3
    assert settings.command_clip_fps == 25
    assert settings.command_confidence_threshold == 0.85
    assert settings.command_top1_margin == 0.20
    assert settings.prototype_prefer_personal is False
    assert settings.allow_global_profile_write is True
    assert settings.log_level == "INFO"
    assert settings.debug_dump_windows is False

def test_create_app_registers_health_routes():
    app = create_app(Settings())
    route_paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/health/live" in route_paths
    assert "/health/ready" in route_paths


def test_create_app_configures_application_info_logging():
    import logging

    create_app(Settings(log_level="INFO"))

    assert logging.getLogger("command").isEnabledFor(logging.INFO)


def test_ready_route_reports_fake_models_ready():
    from fastapi.testclient import TestClient

    app = create_app(Settings(command_backend="fake"))
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    assert response.json()["models"] == {"backend": "fake", "ready": True}
