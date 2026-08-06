import json
import sqlite3
from pathlib import Path

import yaml

import api.backup as backup_api
import services.database_registry as registry
import services.llm_engine.manager as llm_manager
from app.dependencies.auth import ADMIN_API_KEY
from main import app
from services.db import close_connection, init_db
from tests.asgi_client import asgi_request


EXPECTED_EVENTS = {
    "ai.config.update",
    "backup.create",
    "prompt_profile.update",
    "chapter.save",
    "import.confirm",
}


def test_audit_log_covers_high_risk_workflows(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    databases_root = runtime_root / "databases"
    registry_path = runtime_root / "registry.db"
    config_path = runtime_root / "config.local.yaml"
    backup_root = runtime_root / "backups"
    runtime_root.mkdir()

    config_path.write_text(
        yaml.safe_dump(
            {
                "app": {"workspace_id": "bl00"},
                "llm": {"mode": "disabled", "initialized": False},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(registry, "REGISTRY_PATH", str(registry_path))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(databases_root))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(runtime_root / "missing.db"))
    registry.init_registry()
    init_db()
    database_path = Path(registry.get_db_path("default"))

    monkeypatch.setattr(llm_manager, "get_runtime_config_path", lambda: config_path)
    monkeypatch.setattr(llm_manager, "get_writable_config_path", lambda: config_path)

    monkeypatch.setattr(backup_api, "BACKUP_DIR", str(backup_root))
    monkeypatch.setattr(backup_api, "get_runtime_config_path", lambda: config_path)

    headers = {"X-API-Key": ADMIN_API_KEY}

    assert asgi_request(
        app,
        "POST",
        "/api/ai/config",
        headers=headers,
        json_body={"mode": "disabled", "initialized": False},
    )[0] == 200

    backup_status, _ = asgi_request(
        app,
        "POST",
        "/api/backup/create",
        headers=headers,
        params={"description": "BL-00 isolated audit test"},
    )
    assert backup_status == 200

    profile_id = "bl00_profile"
    assert asgi_request(
        app,
        "POST",
        "/api/prompts/profiles",
        headers=headers,
        json_body={"profile_id": profile_id, "name": "BL-00", "content": "draft"},
    )[0] == 200
    assert asgi_request(
        app,
        "PUT",
        f"/api/prompts/profiles/{profile_id}",
        headers=headers,
        json_body={"name": "BL-00 updated", "content": "revised"},
    )[0] == 200

    with sqlite3.connect(database_path) as conn:
        conn.execute(
            "INSERT INTO chapters(chapter_id,book_id,title,chapter_index) VALUES (?,?,?,?)",
            ("CHP_BL00", "default", "BL-00 chapter", 1),
        )
        conn.commit()
    assert asgi_request(
        app,
        "PUT",
        "/api/chapters/CHP_BL00",
        headers=headers,
        params={"title": "BL-00 chapter updated", "content": "isolated content"},
    )[0] == 200

    assert asgi_request(
        app,
        "POST",
        "/api/import/confirm",
        headers=headers,
        json_body={
            "entities": [
                {
                    "title": "BL-00 imported entity",
                    "type": "concept",
                    "content": "isolated import",
                    "tags": ["bl00"],
                    "importance": 1,
                }
            ],
            "relations": [],
        },
    )[0] == 200

    close_connection()
    with sqlite3.connect(database_path) as conn:
        rows = conn.execute(
            "SELECT event_type, description, details FROM audit_log ORDER BY log_id"
        ).fetchall()

    event_types = {row[0] for row in rows}
    assert EXPECTED_EVENTS <= event_types

    evidence = json.dumps(rows, ensure_ascii=False).lower()
    for marker in (
        "authorization",
        "x-api-key",
        "bearer",
        "sk-",
        "nvk_",
        "api_key",
        "password",
    ):
        assert marker not in evidence

    generated_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in runtime_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".json", ".yaml", ".yml", ".log", ".txt"}
    ).lower()
    for marker in ("authorization", "x-api-key", "bearer", "sk-", "nvk_", "api_key", "password"):
        assert marker not in generated_text
