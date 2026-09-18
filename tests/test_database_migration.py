import sqlite3
from pathlib import Path

from buildguard.storage.database import SCHEMA_VERSION, Database
from buildguard.storage.repositories import Repositories


def test_new_database_version_idempotence_and_uploaded_evidence_crud(
    tmp_path: Path,
) -> None:
    path = tmp_path / "buildguard.db"
    database = Database(path)
    database.initialize()
    database.initialize()

    status = database.check()
    assert status["schema_version"] == SCHEMA_VERSION
    assert "uploaded_evidence" in status["tables"]
    with database.session() as session:
        repository = Repositories(session).uploaded_evidence
        created = repository.create(
            evidence_id="evidence-1",
            storage_path="/allowed/random.png",
            original_name="original.png",
            mime_type="image/png",
            sha256="a" * 64,
            size_bytes=10,
            width=2,
            height=5,
        )
        entity_id = created.id
    with database.session() as session:
        repository = Repositories(session).uploaded_evidence
        assert repository.get(entity_id) is not None
        assert repository.update(entity_id, width=3).width == 3
        assert repository.delete(entity_id) is True
        assert repository.get(entity_id) is None


def test_legacy_database_is_backed_up_and_upgraded(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO sessions (id) VALUES ('preserved')")
    original = path.read_bytes()

    database = Database(path)
    database.initialize()

    backup = path.with_suffix(f".db.pre-v{SCHEMA_VERSION}.bak")
    assert backup.read_bytes() == original
    assert database.check()["schema_version"] == SCHEMA_VERSION
    assert "uploaded_evidence" in database.check()["tables"]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT id FROM sessions").fetchone() == (
            "preserved",
        )
