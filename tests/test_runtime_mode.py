from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from buildguard.api.routes_runtime import create_runtime_router
from buildguard.config import RuntimeModeConfig
from buildguard.runtime_mode import (
    RuntimeMode,
    RuntimeModeConflict,
    RuntimeModeManager,
)


def _manager(tmp_path: Path) -> RuntimeModeManager:
    return RuntimeModeManager(RuntimeModeConfig(), tmp_path / "workspace")


def test_runtime_mode_transitions_conflicts_and_audit(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    assert manager.status().mode == RuntimeMode.ONLINE
    indexing = manager.enter(RuntimeMode.INDEXING)
    assert indexing.mode == RuntimeMode.INDEXING
    try:
        manager.enter(RuntimeMode.TRAINING)
    except RuntimeModeConflict:
        pass
    else:
        raise AssertionError("conflicting mode was not rejected")
    online = manager.leave()

    assert online.mode == RuntimeMode.ONLINE
    assert online.generation == 2
    assert manager.audit_path.read_text(encoding="utf-8").count("\n") == 2


def test_runtime_mode_recovers_corrupt_state(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.state_path.parent.mkdir(parents=True)
    manager.state_path.write_text("{broken", encoding="utf-8")

    state = manager.status()

    assert state.mode == RuntimeMode.ONLINE
    assert state.recovered is True
    assert list(manager.state_path.parent.glob("runtime-mode.json.corrupt-*"))
    assert '"action":"recover"' in manager.audit_path.read_text(encoding="utf-8")


def test_runtime_mode_file_lock_serializes_competing_enters(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    def enter(mode: RuntimeMode) -> str:
        try:
            return manager.enter(mode).mode.value
        except RuntimeModeConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(enter, [RuntimeMode.INDEXING, RuntimeMode.TRAINING])
        )

    assert sorted(results).count("conflict") == 1
    assert manager.status().mode in {RuntimeMode.INDEXING, RuntimeMode.TRAINING}


def test_runtime_mode_api_reports_conflict(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    app = FastAPI()
    app.include_router(create_runtime_router(manager))
    client = TestClient(app)

    assert client.get("/runtime-mode").json()["mode"] == "online"
    assert client.post("/runtime-mode/enter/indexing").status_code == 200
    conflict = client.post("/runtime-mode/enter/training")
    assert conflict.status_code == 409
    assert client.post("/runtime-mode/leave").json()["mode"] == "online"
