import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from buildguard.config import RetentionConfig
from buildguard.logging_system.jsonl_writer import JsonlWriter, atomic_write_json
from buildguard.schemas.common import BoundingBox
from buildguard.schemas.tools import AuditRecord
from buildguard.storage.database import SCHEMA_VERSION, Database
from buildguard.storage.repositories import Repositories
from buildguard.workspace.manager import WorkspaceManager
from buildguard.workspace.retention import RetentionCleaner


def test_bounding_box_geometry_and_validation() -> None:
    box = BoundingBox(x1=10, y1=10, x2=30, y2=40)
    other = BoundingBox(x1=20, y1=20, x2=40, y2=50)
    assert box.width == 20
    assert box.height == 30
    assert box.area == 600
    assert box.iou(other) == pytest.approx(200 / 1000)
    assert box.clip(25, 35) == BoundingBox(x1=10, y1=10, x2=25, y2=35)
    with pytest.raises(ValidationError, match="x2 must be greater"):
        BoundingBox(x1=5, y1=0, x2=4, y2=2)


def test_database_initialization_and_repository_crud(tmp_path: Path) -> None:
    database = Database(tmp_path / "database" / "test.db")
    database.initialize()
    check = database.check()
    assert check["ok"] is True
    assert "sessions" in check["tables"]
    assert check["schema_version"] == SCHEMA_VERSION
    assert {
        "camera_statuses",
        "realtime_events",
        "verified_facts",
        "remediation_records",
    } <= set(check["tables"])
    with database.session() as session:
        repositories = Repositories(session)
        created = repositories.sessions.create(title="Site A")
        entity_id = created.id
        assert repositories.sessions.get(entity_id) is created
        repositories.sessions.update(entity_id, title="Site B")
        assert repositories.sessions.list()[0].title == "Site B"
    with database.session() as session:
        repository = Repositories(session).sessions
        reloaded = repository.get(entity_id)
        assert reloaded is not None
        assert reloaded.created_at.tzinfo is UTC
        assert repository.delete(entity_id)
    database.dispose()


def test_database_uses_uuid_and_utc_default(tmp_path: Path) -> None:
    database = Database(tmp_path / "utc.db")
    database.initialize()
    with database.session() as session:
        entity = Repositories(session).sessions.create(title="UTC")
        assert len(entity.id) == 36
        assert entity.created_at.tzinfo is UTC
    database.dispose()


def test_jsonl_thread_safe_shape_and_redaction(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    record = AuditRecord(
        actor="tester",
        action="login",
        resource="local",
        outcome="success",
        details={"password": "bad", "nested": {"api_key": "secret"}, "safe": "visible"},
    )
    with JsonlWriter(path) as writer:
        writer.write(record)
        writer.flush()
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["details"]["password"] == "********"
    assert parsed["details"]["nested"]["api_key"] == "********"
    assert parsed["details"]["safe"] == "visible"


def test_atomic_summary_replaces_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    path.write_text('{"old":true}', encoding="utf-8")
    atomic_write_json(path, {"new": True, "token": "secret"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True, "token": "********"}
    assert list(tmp_path.glob("*.tmp")) == []


def test_workspace_is_idempotent_and_blocks_escape(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspace")
    first = manager.initialize()
    second = manager.initialize()
    assert first == second
    assert first["events/images"].is_absolute()
    with pytest.raises(ValueError, match="escapes workspace"):
        manager.resolve("../outside")
    with pytest.raises(ValueError, match="escapes workspace"):
        manager.resolve(tmp_path.parent / "absolute-outside")


def test_retention_dry_run_does_not_delete(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspace")
    paths = manager.initialize()
    old = paths["events/images"] / "old.jpg"
    old.write_bytes(b"image")
    timestamp = (datetime.now(UTC) - timedelta(days=10)).timestamp()
    os.utime(old, (timestamp, timestamp))
    cleaner = RetentionCleaner(manager, RetentionConfig(event_images_days=1))
    result = cleaner.cleanup(dry_run=True)
    assert old.resolve() in result.candidates
    assert result.deleted == []
    assert old.exists()
    with pytest.raises(ValueError, match="disabled"):
        cleaner.cleanup(dry_run=False)
