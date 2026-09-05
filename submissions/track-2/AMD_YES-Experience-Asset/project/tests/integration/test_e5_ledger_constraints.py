"""Database-level probes for the relation ledger.

Model validators run in one process on one object. They cannot stop a second
writer, a repair script or a future ticket from inserting a row that splices two
assets together, and they cannot make a deleted summary stop being searchable.
These tests exercise the schema directly, without going through the models, so a
constraint that exists only in Python is visible as a gap here.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.experience_asset.domain.factory import new_empty_asset
from app.experience_asset.persistence import SQLiteAssetRepository

NOW = datetime.now(UTC).isoformat()


@pytest.fixture
def ledger(tmp_path) -> tuple[sqlite3.Connection, dict]:
    """Two real assets, so cross-asset splicing has something to splice."""
    database_path: Path = tmp_path / "ledger.sqlite3"
    repository = SQLiteAssetRepository(database_path)
    repository.initialize()
    assets = {}
    for name in ("a", "b"):
        snapshot = new_empty_asset(
            asset_id=uuid4(), version_id=uuid4(), now=datetime.now(UTC)
        )
        repository.create(snapshot)
        assets[name] = snapshot

    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.commit()
    return connection, assets


def _insert_projection(
    connection: sqlite3.Connection, *, projection_id: str, asset_id, version_id
) -> None:
    connection.execute(
        """
        INSERT INTO role_graph_projections(
            projection_id, asset_id, version_id, knowledge_card_hash,
            projection_schema_version, projection_hash, lifecycle, created_at
        ) VALUES (?, ?, ?, ?, 'e5-role-graph/v1', ?, 'ACTIVE', ?)
        """,
        (projection_id, str(asset_id), str(version_id), "a" * 64, "b" * 64, NOW),
    )


def test_projection_cannot_claim_another_assets_version(ledger) -> None:
    """The probe the review used: splice asset B onto asset A's version.

    A single-column reference only proves the version row exists somewhere. It
    would let a projection built from asset A's content present itself as asset
    B's, and readiness, permission and invalidation all key off that pairing.
    """
    connection, assets = ledger
    with pytest.raises(sqlite3.IntegrityError):
        _insert_projection(
            connection,
            projection_id="p-spliced",
            asset_id=assets["b"].asset_id,
            version_id=assets["a"].version_id,
        )


def test_projection_accepts_its_own_assets_version(ledger) -> None:
    """Guard the guard: the constraint must not reject valid rows."""
    connection, assets = ledger
    _insert_projection(
        connection,
        projection_id="p-valid",
        asset_id=assets["a"].asset_id,
        version_id=assets["a"].version_id,
    )
    connection.commit()


def test_readiness_cannot_span_two_assets(ledger) -> None:
    connection, assets = ledger
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO knowledge_card_readiness(
                readiness_id, asset_id, version_id, m4_artifact_id,
                knowledge_card_hash, milestone_state, content_json,
                lifecycle, accepted_at
            ) VALUES (?, ?, ?, ?, ?, 'CONFIRMED', '{}', 'ACTIVE', ?)
            """,
            (
                "r-spliced",
                str(assets["b"].asset_id),
                str(assets["a"].version_id),
                "m4-nonexistent",
                "a" * 64,
                NOW,
            ),
        )


def test_readiness_rejects_active_with_invalidation_evidence(ledger) -> None:
    """An ACTIVE row carrying an invalidation time has no fail-closed reading."""
    connection, assets = ledger
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO knowledge_card_readiness(
                readiness_id, asset_id, version_id, m4_artifact_id,
                knowledge_card_hash, milestone_state, content_json,
                lifecycle, accepted_at, invalidated_at, invalidation_reason
            ) VALUES (?, ?, ?, ?, ?, 'CONFIRMED', '{}', 'ACTIVE', ?, ?, 'x')
            """,
            (
                "r-contradictory",
                str(assets["a"].asset_id),
                str(assets["a"].version_id),
                "m4-x",
                "a" * 64,
                NOW,
                NOW,
            ),
        )


def test_readiness_has_no_building_state(ledger) -> None:
    """Readiness is minted whole by one explicit acceptance."""
    connection, assets = ledger
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO knowledge_card_readiness(
                readiness_id, asset_id, version_id, m4_artifact_id,
                knowledge_card_hash, milestone_state, content_json,
                lifecycle, accepted_at
            ) VALUES (?, ?, ?, ?, ?, 'CONFIRMED', '{}', 'BUILDING', ?)
            """,
            (
                "r-building",
                str(assets["a"].asset_id),
                str(assets["a"].version_id),
                "m4-x",
                "a" * 64,
                NOW,
            ),
        )


def _index_summary(connection: sqlite3.Connection, projection_id: str, asset_id) -> None:
    connection.execute(
        """
        INSERT INTO relation_summary_fts(
            projection_id, asset_id, asset_title, summary_text,
            lexical_tokens, role_signature
        ) VALUES (?, ?, '私密标题', '私密摘要正文', 'tok', 'sig')
        """,
        (projection_id, str(asset_id)),
    )


def _summary_hits(connection: sqlite3.Connection) -> int:
    return connection.execute(
        "SELECT count(*) FROM relation_summary_fts "
        "WHERE relation_summary_fts MATCH '私密摘要正文'"
    ).fetchone()[0]


def test_deleting_a_projection_removes_its_indexed_summary(ledger) -> None:
    """The review's Critical finding: deletion must not leave text searchable.

    An FTS5 table holds its own copy of the indexed text. Nothing removes that
    copy when the row it came from disappears, so without the trigger a deletion
    looks complete while the content it was meant to remove is still readable.
    """
    connection, assets = ledger
    _insert_projection(
        connection,
        projection_id="p-del",
        asset_id=assets["a"].asset_id,
        version_id=assets["a"].version_id,
    )
    _index_summary(connection, "p-del", assets["a"].asset_id)
    assert _summary_hits(connection) == 1

    connection.execute("DELETE FROM role_graph_projections WHERE projection_id = 'p-del'")
    connection.commit()

    assert _summary_hits(connection) == 0


def test_leaving_active_removes_the_indexed_summary(ledger) -> None:
    """Eligibility and the index must end together.

    An index row that outlives eligibility still matches for canonical state
    that has since changed, so a stale summary could be compared against.
    """
    connection, assets = ledger
    _insert_projection(
        connection,
        projection_id="p-stale",
        asset_id=assets["a"].asset_id,
        version_id=assets["a"].version_id,
    )
    _index_summary(connection, "p-stale", assets["a"].asset_id)
    assert _summary_hits(connection) == 1

    connection.execute(
        "UPDATE role_graph_projections SET lifecycle='STALE', invalidated_at=?, "
        "invalidation_reason='asset corrected' WHERE projection_id='p-stale'",
        (NOW,),
    )
    connection.commit()

    assert _summary_hits(connection) == 0


def test_deleting_an_asset_removes_its_indexed_summaries(ledger) -> None:
    """Privacy deletion must reach the index, which is not a child of anything."""
    connection, assets = ledger
    _insert_projection(
        connection,
        projection_id="p-asset",
        asset_id=assets["a"].asset_id,
        version_id=assets["a"].version_id,
    )
    _index_summary(connection, "p-asset", assets["a"].asset_id)
    connection.commit()
    assert _summary_hits(connection) == 1

    connection.execute(
        "DELETE FROM assets WHERE asset_id = ?", (str(assets["a"].asset_id),)
    )
    connection.commit()

    assert _summary_hits(connection) == 0


def test_projection_rejects_active_with_invalidation_evidence(ledger) -> None:
    connection, assets = ledger
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO role_graph_projections(
                projection_id, asset_id, version_id, knowledge_card_hash,
                projection_schema_version, projection_hash, lifecycle,
                created_at, invalidated_at, invalidation_reason
            ) VALUES (?, ?, ?, ?, 'e5-role-graph/v1', ?, 'ACTIVE', ?, ?, 'x')
            """,
            (
                "p-contradictory",
                str(assets["a"].asset_id),
                str(assets["a"].version_id),
                "a" * 64,
                "b" * 64,
                NOW,
                NOW,
            ),
        )
