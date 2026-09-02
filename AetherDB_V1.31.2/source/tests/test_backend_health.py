from main import BACKEND_BUILD_ID, RUNTIME_INSTANCE_ID, app, backend_health_payload


def test_backend_health_contract_reports_identity_version_and_database_state():
    previous = app.state.database_ready
    try:
        app.state.database_ready = True
        payload = backend_health_payload()
    finally:
        app.state.database_ready = previous

    assert payload == {
        "status": "ok",
        "service": "aetherdb-backend",
        "version": "1.31.2",
        "build_id": BACKEND_BUILD_ID,
        "instance_id": RUNTIME_INSTANCE_ID,
        "database_ready": True,
    }
    assert RUNTIME_INSTANCE_ID.startswith("aether_runtime_")
    assert len(RUNTIME_INSTANCE_ID) == 47


def test_backend_health_fails_readiness_closed_before_database_initialization():
    previous = app.state.database_ready
    try:
        app.state.database_ready = False
        payload = backend_health_payload()
    finally:
        app.state.database_ready = previous

    assert payload["status"] == "starting"
    assert payload["database_ready"] is False
