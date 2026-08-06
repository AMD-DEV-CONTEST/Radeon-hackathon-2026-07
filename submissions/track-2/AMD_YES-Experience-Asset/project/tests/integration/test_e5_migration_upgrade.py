"""Upgrade path from the pre-E5 schema to the relation-ledger schema.

Every test in the existing suite builds its assets from the *current* model, so
none of them ever reads a row written under an older shape. That blind spot let
the relation-field retirement make all previously accepted history unreadable
while the suite stayed green. These tests read rows this session did not write.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.experience_asset.domain.factory import new_empty_asset
from app.experience_asset.domain.models import ExperienceAssetV1
from app.experience_asset.persistence import SQLiteAssetRepository

PRE_E5_MIGRATION_LIMIT = 7
RETIRED_SNAPSHOT_FIELDS = (
    "related_assets",
    "knowledge_card_readiness",
    "relation_candidates",
    "relation_candidate_decisions",
)


def _apply_migrations_up_to(database_path: Path, limit: int) -> None:
    """Build a database at an older schema version, without E5 tables."""
    migration_dir = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "experience_asset"
        / "persistence"
        / "migrations"
    )
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    for migration in sorted(migration_dir.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        version = int(migration.name.split("_", maxsplit=1)[0])
        if version > limit:
            continue
        connection.executescript(migration.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, datetime.now(UTC).isoformat()),
        )
    connection.commit()
    connection.close()


def _pre_e5_snapshot_json(snapshot: ExperienceAssetV1) -> str:
    """Serialize a snapshot the way the pre-E5 model would have."""
    payload = snapshot.model_dump(mode="json")
    payload["related_assets"] = []
    payload["knowledge_card_readiness"] = None
    payload["relation_candidates"] = []
    payload["relation_candidate_decisions"] = []
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _insert_pre_e5_version(
    database_path: Path, snapshot: ExperienceAssetV1, content_json: str
) -> None:
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        INSERT INTO assets(asset_id, lifecycle, current_version_id, created_at, updated_at)
        VALUES (?, ?, NULL, ?, ?)
        """,
        (
            str(snapshot.asset_id),
            snapshot.lifecycle.value,
            snapshot.created_at.isoformat(),
            snapshot.updated_at.isoformat(),
        ),
    )
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(asset_versions)")
    }
    values = {
        "version_id": str(snapshot.version_id),
        "asset_id": str(snapshot.asset_id),
        "parent_version_id": None,
        "schema_version": snapshot.schema_version,
        "change_kind": snapshot.lineage.change_kind,
        "change_reason": snapshot.lineage.change_reason,
        "created_at": snapshot.created_at.isoformat(),
        "content_json": content_json,
        "content_hash": "0" * 64,
        "derived_by_run_id": None,
    }
    usable = [name for name in values if name in columns]
    connection.execute(
        f"INSERT INTO asset_versions({', '.join(usable)}) "
        f"VALUES ({', '.join('?' for _ in usable)})",
        [values[name] for name in usable],
    )
    connection.execute(
        "UPDATE assets SET current_version_id = ? WHERE asset_id = ?",
        (str(snapshot.version_id), str(snapshot.asset_id)),
    )
    connection.commit()
    connection.close()


@pytest.fixture
def pre_e5_database(tmp_path) -> tuple[Path, ExperienceAssetV1, str]:
    database_path = tmp_path / "pre-e5.sqlite3"
    _apply_migrations_up_to(database_path, PRE_E5_MIGRATION_LIMIT)
    snapshot = new_empty_asset(
        asset_id=uuid4(), version_id=uuid4(), now=datetime.now(UTC)
    )
    content_json = _pre_e5_snapshot_json(snapshot)
    _insert_pre_e5_version(database_path, snapshot, content_json)
    return database_path, snapshot, content_json


def test_pre_e5_schema_lacks_the_relation_ledger(pre_e5_database) -> None:
    """Guard the fixture itself: it must really be an older schema."""
    database_path, _, content_json = pre_e5_database
    connection = sqlite3.connect(database_path)
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    connection.close()
    assert "role_graph_projections" not in tables
    assert "knowledge_card_readiness" not in tables
    for field in RETIRED_SNAPSHOT_FIELDS:
        assert field in content_json


def test_upgrade_reads_accepted_history_written_before_the_relation_ledger(
    pre_e5_database,
) -> None:
    database_path, snapshot, _ = pre_e5_database

    repository = SQLiteAssetRepository(database_path)
    repository.initialize()

    restored = repository.get_current(snapshot.asset_id)
    assert restored.asset_id == snapshot.asset_id
    assert restored.version_id == snapshot.version_id
    assert restored.milestone_states == snapshot.milestone_states
    assert len(restored.route_decisions) == len(snapshot.route_decisions)


def test_upgrade_leaves_stored_history_byte_identical(pre_e5_database) -> None:
    """Accepted history is never rewritten, so its content hash cannot drift."""
    database_path, snapshot, content_json = pre_e5_database

    SQLiteAssetRepository(database_path).initialize()

    connection = sqlite3.connect(database_path)
    stored, stored_hash = connection.execute(
        "SELECT content_json, content_hash FROM asset_versions WHERE version_id = ?",
        (str(snapshot.version_id),),
    ).fetchone()
    connection.close()

    assert stored == content_json
    assert stored_hash == "0" * 64


def test_upgrade_adds_the_relation_ledger_and_records_its_version(
    pre_e5_database,
) -> None:
    database_path, _, _ = pre_e5_database

    SQLiteAssetRepository(database_path).initialize()

    connection = sqlite3.connect(database_path)
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    run_context_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(workflow_run_contexts)")
    }
    applied = [
        row[0]
        for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
    ]
    connection.close()

    for table in (
        "m4_artifacts",
        "knowledge_card_readiness",
        "role_graph_projections",
        "role_graph_nodes",
        "role_graph_edges",
        "role_graph_node_provenance",
        "relation_summary_fts",
        "relation_discovery_attempts",
        "relation_candidates",
        "relation_candidate_decisions",
        "confirmed_asset_relations",
        # Ticket 02's run bookkeeping. 0008 froze the M4 artifact tables but not
        # the run-side tables the M3 slice received in 0006, so an M4 run had
        # nowhere to record the proposal it validates, nothing to make its
        # commit idempotent across a restart, and no durable copy of the context
        # bound its acceptance criteria require to be recorded.
        "m4_model_proposals",
        "m4_run_commits",
        "m4_policy_decisions",
        # Ticket 03/04/08: the product path emits into the frozen
        # retrieval-phase-trace shape; before this it had no producer
        # outside the E2 evidence-capture script.
        "retrieval_phase_events",
    ):
        assert table in tables, f"migration did not create {table}"
    assert {
        "base_m3_artifact_id",
        "m4_regenerate",
        "expected_invalidated_m4_artifact_id",
        "m4_context_bound_json",
    } <= run_context_columns
    assert applied == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]


def test_upgrade_is_idempotent(pre_e5_database) -> None:
    database_path, snapshot, _ = pre_e5_database

    SQLiteAssetRepository(database_path).initialize()
    SQLiteAssetRepository(database_path).initialize()

    assert SQLiteAssetRepository(database_path).get_current(snapshot.asset_id).version_id == (
        snapshot.version_id
    )


def test_snapshot_carrying_real_relation_state_fails_loudly(pre_e5_database) -> None:
    """Silently discarding relation state would be undetectable afterwards.

    Empty retired fields are dropped because nothing is lost. A populated one is
    a different situation: dropping it would destroy state with no trace, so the
    load fails and names the fields instead.
    """
    _, snapshot, _ = pre_e5_database
    payload = json.loads(_pre_e5_snapshot_json(snapshot))
    payload["relation_candidates"] = [
        {
            "candidate_id": str(uuid4()),
            "related_asset_id": str(uuid4()),
            "title": "legacy candidate",
            "summary": "legacy summary",
            "proposed_relation": "SIMILAR_SITUATION",
            "reason": "legacy reason",
            "provenance_refs": ["legacy:ref"],
            "detail_included": False,
        }
    ]

    with pytest.raises(ValueError) as excinfo:
        ExperienceAssetV1.model_validate(payload)

    message = str(excinfo.value)
    assert "relation_candidates" in message
    assert "relation ledger" in message


@pytest.mark.parametrize("field", RETIRED_SNAPSHOT_FIELDS)
def test_each_retired_field_is_accepted_when_empty(pre_e5_database, field) -> None:
    _, snapshot, _ = pre_e5_database
    payload = snapshot.model_dump(mode="json")
    payload[field] = None if field == "knowledge_card_readiness" else []

    restored = ExperienceAssetV1.model_validate(payload)

    assert restored.version_id == snapshot.version_id
    assert not hasattr(restored, field)


def test_unknown_fields_are_still_rejected(pre_e5_database) -> None:
    """The shim drops four named keys, not arbitrary ones.

    Relaxing `extra="forbid"` wholesale would make a misspelled field name a
    silent no-op instead of an error, which is a worse failure than the one
    being fixed.
    """
    _, snapshot, _ = pre_e5_database
    payload = snapshot.model_dump(mode="json")
    payload["relation_candidatez"] = []

    with pytest.raises(ValueError, match="relation_candidatez"):
        ExperienceAssetV1.model_validate(payload)


def test_a_rewritten_migration_is_reported_not_silently_skipped(tmp_path) -> None:
    """Migration 0008 was rewritten several times during the E5 contract freeze.

    A runner that keys only on the version number cannot tell a rewritten
    migration from the one that actually ran, so a database created from an
    earlier 0008 keeps its old schema while the code assumes the new
    constraints are enforced. Nothing reports it: the schema and the contract
    disagree with no symptom until a write that should fail succeeds.
    """
    from app.experience_asset.persistence import StorageConflictError

    database_path = tmp_path / "rewritten.sqlite3"
    SQLiteAssetRepository(database_path).initialize()

    connection = sqlite3.connect(database_path)
    connection.execute(
        "UPDATE schema_migrations SET checksum = ? WHERE version = 8",
        ("0" * 64,),
    )
    connection.commit()
    connection.close()

    with pytest.raises(StorageConflictError, match="0008"):
        SQLiteAssetRepository(database_path).initialize()


def test_an_unchanged_migration_set_reinitializes_cleanly(tmp_path) -> None:
    """Paired positive: the checksum must not reject an untouched database."""
    database_path = tmp_path / "unchanged.sqlite3"
    SQLiteAssetRepository(database_path).initialize()
    SQLiteAssetRepository(database_path).initialize()
