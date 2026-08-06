"""Identity-chain probes over the whole relation ledger.

Every negative builds all legitimate parent rows first, changes only the field
under test, and is paired with a positive on the same fixture. A negative that
fails for an unrelated missing parent is worse than no test: it stays green if
the constraint it claims to cover is deleted, so it reports coverage the suite
does not have.

Each asset carries **two** versions and **two** projections. Cross-asset swaps
are the easy case; the dangerous one is a swap inside a single asset, where
nothing crosses an asset boundary and every per-asset check still passes while
the row describes inputs the user never saw.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.experience_asset.domain.factory import new_empty_asset
from app.experience_asset.persistence import SQLiteAssetRepository

NOW = datetime.now(UTC).isoformat()
LATER = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
FINGERPRINT = "c" * 64
OTHER_FINGERPRINT = "d" * 64
CARD_V1 = "a" * 64
CARD_V2 = "e" * 64


@pytest.fixture
def chain(tmp_path):
    """Two assets, each with two versions, two readiness rows, two projections."""
    database_path = tmp_path / "chain.sqlite3"
    repository = SQLiteAssetRepository(database_path)
    repository.initialize()

    ids: dict[str, dict] = {}
    for name in ("a", "b"):
        snapshot = new_empty_asset(
            asset_id=uuid4(), version_id=uuid4(), now=datetime.now(UTC)
        )
        repository.create(snapshot)
        ids[name] = {
            "asset": snapshot.asset_id,
            "v1": snapshot.version_id,
            "v2": uuid4(),
        }

    db = sqlite3.connect(database_path)
    db.execute("PRAGMA foreign_keys = ON")
    version_columns = [row[1] for row in db.execute("PRAGMA table_info(asset_versions)")]

    for name, entry in ids.items():
        asset = str(entry["asset"])
        values = {
            "version_id": str(entry["v2"]),
            "asset_id": asset,
            "parent_version_id": str(entry["v1"]),
            "schema_version": "1.0.0",
            "change_kind": "USER_EDIT",
            "change_reason": "second accepted version",
            "created_at": NOW,
            "content_json": "{}",
            "content_hash": "0" * 64,
            "derived_by_run_id": None,
        }
        usable = [column for column in values if column in version_columns]
        db.execute(
            f"INSERT INTO asset_versions({', '.join(usable)}) "
            f"VALUES ({', '.join('?' for _ in usable)})",
            [values[column] for column in usable],
        )

        db.execute(
            "INSERT INTO m2_artifacts(artifact_id, asset_id, parent_artifact_id, "
            "base_m1_version_id, content_json, created_at) "
            "VALUES (?, ?, NULL, ?, '{}', ?)",
            (f"m2-{name}", asset, str(entry["v1"]), NOW),
        )
        db.execute(
            "INSERT INTO m3_artifacts(artifact_id, asset_id, parent_artifact_id, "
            "base_m2_artifact_id, base_canonical_version_id, content_json, created_at) "
            "VALUES (?, ?, NULL, ?, ?, '{}', ?)",
            (f"m3-{name}", asset, f"m2-{name}", str(entry["v1"]), NOW),
        )
        for slot in ("v1", "v2"):
            version = str(entry[slot])
            card = CARD_V1 if slot == "v1" else CARD_V2
            db.execute(
                "INSERT INTO m4_artifacts(artifact_id, asset_id, parent_artifact_id, "
                "base_m3_artifact_id, base_canonical_version_id, content_json, created_at) "
                "VALUES (?, ?, NULL, ?, ?, '{}', ?)",
                (f"m4-{name}-{slot}", asset, f"m3-{name}", version, NOW),
            )
            db.execute(
                "INSERT INTO knowledge_card_readiness(readiness_id, asset_id, version_id, "
                "m4_artifact_id, knowledge_card_hash, milestone_state, content_json, "
                "lifecycle, accepted_at) "
                "VALUES (?, ?, ?, ?, ?, 'CONFIRMED', '{}', 'ACTIVE', ?)",
                (f"rd-{name}-{slot}", asset, version, f"m4-{name}-{slot}", card, NOW),
            )
            db.execute(
                "INSERT INTO role_graph_projections(projection_id, asset_id, version_id, "
                "knowledge_card_hash, projection_schema_version, projection_hash, "
                "lifecycle, created_at) "
                "VALUES (?, ?, ?, ?, 'e5-role-graph/v1', ?, 'ACTIVE', ?)",
                (
                    f"proj-{name}-{slot}",
                    asset,
                    version,
                    card,
                    f"{name}{slot}".ljust(64, "0"),
                    NOW,
                ),
            )
    db.commit()
    return db, ids


def _candidate(
    db,
    ids,
    *,
    cid,
    current="a",
    related="b",
    relation_type="METHOD_REUSE",
    fingerprint=FINGERPRINT,
    current_projection=None,
    historical_projection=None,
):
    """Insert a candidate, naming each side's projection explicitly.

    An earlier version of this helper picked the projection with a condition
    that was always true, so every candidate used the same one whatever side it
    claimed. A helper that cannot express the wrong value cannot be used to test
    that the wrong value is rejected.
    """
    db.execute(
        "INSERT INTO relation_candidates(candidate_id, discovery_fingerprint, "
        "current_asset_id, current_projection_id, related_asset_id, "
        "historical_projection_id, relation_type, validation_contract_version, "
        "lifecycle, content_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'e5-relation/v1', 'PROPOSED', '{}', ?)",
        (
            cid,
            fingerprint,
            str(ids[current]["asset"]),
            current_projection or f"proj-{current}-v1",
            str(ids[related]["asset"]),
            historical_projection or f"proj-{related}-v1",
            relation_type,
            NOW,
        ),
    )


def _decision(
    db, ids, *, did, cid, current="a", related="b", version="v1", card=CARD_V1,
    projection=None, action="CONFIRM",
):
    db.execute(
        "INSERT INTO relation_candidate_decisions(decision_id, candidate_id, "
        "current_asset_id, current_version_id, current_knowledge_card_hash, "
        "current_projection_id, related_asset_id, user_action, decided_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            did,
            cid,
            str(ids[current]["asset"]),
            str(ids[current][version]),
            card,
            projection or f"proj-{current}-v1",
            str(ids[related]["asset"]),
            action,
            NOW,
        ),
    )


def _confirmed(
    db,
    ids,
    *,
    rid,
    cid,
    did,
    current="a",
    related="b",
    relation_type="METHOD_REUSE",
    fingerprint=FINGERPRINT,
    current_projection=None,
    historical_projection=None,
    current_version="v1",
    related_version="v1",
    card=CARD_V1,
):
    db.execute(
        "INSERT INTO confirmed_asset_relations(relation_id, source_candidate_id, "
        "source_discovery_fingerprint, confirming_decision_id, relation_type, "
        "current_asset_id, current_version_id, current_projection_id, "
        "current_knowledge_card_hash, related_asset_id, related_version_id, "
        "historical_projection_id, lifecycle, confirmed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CONFIRMED', ?)",
        (
            rid,
            cid,
            fingerprint,
            did,
            relation_type,
            str(ids[current]["asset"]),
            str(ids[current][current_version]),
            current_projection or f"proj-{current}-v1",
            card,
            str(ids[related]["asset"]),
            str(ids[related][related_version]),
            historical_projection or f"proj-{related}-v1",
            NOW,
        ),
    )


def _full_ledger(db, ids) -> None:
    """A candidate, its decision and its confirmed relation, all legitimate."""
    _candidate(db, ids, cid="c1")
    _decision(db, ids, did="d1", cid="c1")
    _confirmed(db, ids, rid="r1", cid="c1", did="d1")
    db.commit()


def test_a_complete_legitimate_chain_is_accepted(chain) -> None:
    """The paired positive. Every negative below is meaningful only because this passes."""
    db, ids = chain
    _full_ledger(db, ids)


# --- same-asset splices: nothing crosses an asset boundary -----------------


def test_decision_cannot_use_another_version_of_the_same_asset(chain) -> None:
    """The user answered about v1; recording v2 answers about content they never saw."""
    db, ids = chain
    _candidate(db, ids, cid="c-ver")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _decision(db, ids, did="d-ver", cid="c-ver", version="v2", card=CARD_V2)


def test_decision_cannot_use_an_arbitrary_card_hash(chain) -> None:
    """The hash must name a real readiness row, not any 64 hex characters."""
    db, ids = chain
    _candidate(db, ids, cid="c-hash")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _decision(db, ids, did="d-hash", cid="c-hash", card="f" * 64)


def test_confirmed_cannot_swap_to_another_projection_of_the_same_asset(chain) -> None:
    """`proj-a-v2` belongs to asset A too, so a per-asset check would allow it."""
    db, ids = chain
    _candidate(db, ids, cid="c-proj")
    _decision(db, ids, did="d-proj", cid="c-proj")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _confirmed(
            db, ids, rid="r-proj", cid="c-proj", did="d-proj",
            current_projection="proj-a-v2",
        )


def test_confirmed_cannot_change_the_candidates_fingerprint(chain) -> None:
    """A different fingerprint means a different discovery input entirely."""
    db, ids = chain
    _candidate(db, ids, cid="c-fp")
    _decision(db, ids, did="d-fp", cid="c-fp")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _confirmed(
            db, ids, rid="r-fp", cid="c-fp", did="d-fp",
            fingerprint=OTHER_FINGERPRINT,
        )


def test_confirmed_cannot_change_the_relation_type(chain) -> None:
    db, ids = chain
    _candidate(db, ids, cid="c-type")
    _decision(db, ids, did="d-type", cid="c-type")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _confirmed(
            db, ids, rid="r-type", cid="c-type", did="d-type",
            relation_type="SAME_THEME",
        )


def test_confirmed_requires_a_decision_that_exists(chain) -> None:
    """A relation exists only because the user confirmed; the row must show it."""
    db, ids = chain
    _candidate(db, ids, cid="c-nodec")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _confirmed(db, ids, rid="r-nodec", cid="c-nodec", did="no-such-decision")


def test_attempt_cannot_point_at_a_candidate_from_another_fingerprint(chain) -> None:
    """A cached result would otherwise answer with another search's candidate."""
    db, ids = chain
    _candidate(db, ids, cid="c-att", fingerprint=OTHER_FINGERPRINT)
    _fingerprint(db, ids, FINGERPRINT)
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO relation_discovery_attempts(attempt_id, run_id, asset_id, "
            "discovery_fingerprint, current_projection_id, eligible_set_hash, "
            "attempt_number, outcome, candidate_id, started_at, finished_at) "
            "VALUES ('att-fp', ?, ?, ?, 'proj-a-v1', ?, 1, 'CANDIDATE', 'c-att', ?, ?)",
            (str(uuid4()), str(ids["a"]["asset"]), FINGERPRINT, "b" * 64, NOW, NOW),
        )


# --- deletion with a populated ledger --------------------------------------


@pytest.mark.parametrize("side", ["a", "b"])
def test_deleting_either_side_completes_with_a_full_ledger(chain, side) -> None:
    """A constraint that blocks the delete turns "revoke access" into "request fails".

    That is fail-closed and leaks nothing, but it leaves the user unable to
    remove their own data — and the earlier round's composite keys did exactly
    this once a candidate or relation existed.
    """
    db, ids = chain
    _full_ledger(db, ids)

    db.execute("DELETE FROM assets WHERE asset_id = ?", (str(ids[side]["asset"]),))
    db.commit()

    remaining = db.execute(
        "SELECT (SELECT count(*) FROM relation_candidates) "
        "+ (SELECT count(*) FROM relation_candidate_decisions) "
        "+ (SELECT count(*) FROM confirmed_asset_relations)"
    ).fetchone()[0]
    assert remaining == 0, "ledger rows survived the deletion of a bound asset"


def test_deleting_an_asset_clears_indexed_summaries_with_a_full_ledger(chain) -> None:
    """The FTS trigger only fires if the delete is allowed to run at all."""
    db, ids = chain
    _full_ledger(db, ids)
    db.execute(
        "INSERT INTO relation_summary_fts(projection_id, asset_id, asset_title, "
        "summary_text, lexical_tokens, role_signature) "
        "VALUES ('proj-a-v1', ?, '私密标题', '私密摘要正文', 'tok', 'sig')",
        (str(ids["a"]["asset"]),),
    )
    db.commit()

    db.execute("DELETE FROM assets WHERE asset_id = ?", (str(ids["a"]["asset"]),))
    db.commit()

    hits = db.execute(
        "SELECT count(*) FROM relation_summary_fts "
        "WHERE relation_summary_fts MATCH '私密摘要正文'"
    ).fetchone()[0]
    assert hits == 0


# --- cross-asset splices ----------------------------------------------------


def test_readiness_rejects_another_assets_version(chain) -> None:
    db, ids = chain
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO knowledge_card_readiness(readiness_id, asset_id, version_id, "
            "m4_artifact_id, knowledge_card_hash, milestone_state, content_json, "
            "lifecycle, accepted_at) "
            "VALUES ('r-cross', ?, ?, 'm4-b-v1', ?, 'CONFIRMED', '{}', 'ACTIVE', ?)",
            (str(ids["b"]["asset"]), str(ids["a"]["v1"]), CARD_V1, NOW),
        )


def test_readiness_rejects_building(chain) -> None:
    db, ids = chain
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO knowledge_card_readiness(readiness_id, asset_id, version_id, "
            "m4_artifact_id, knowledge_card_hash, milestone_state, content_json, "
            "lifecycle, accepted_at) "
            "VALUES ('r-build', ?, ?, 'm4-a-v1', ?, 'CONFIRMED', '{}', 'BUILDING', ?)",
            (str(ids["a"]["asset"]), str(ids["a"]["v1"]), "b" * 64, NOW),
        )


def test_m4_parent_cannot_come_from_another_asset(chain) -> None:
    db, ids = chain
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO m4_artifacts(artifact_id, asset_id, parent_artifact_id, "
            "base_m3_artifact_id, base_canonical_version_id, content_json, created_at) "
            "VALUES ('m4-b3', ?, 'm4-a-v1', 'm3-b', ?, '{}', ?)",
            (str(ids["b"]["asset"]), str(ids["b"]["v1"]), NOW),
        )


def test_m4_current_must_point_at_the_same_assets_artifact(chain) -> None:
    db, ids = chain
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO m4_current(asset_id, artifact_id) VALUES (?, 'm4-a-v1')",
            (str(ids["b"]["asset"]),),
        )


def test_m4_current_accepts_its_own_artifact(chain) -> None:
    db, ids = chain
    db.execute(
        "INSERT INTO m4_current(asset_id, artifact_id) VALUES (?, 'm4-b-v1')",
        (str(ids["b"]["asset"]),),
    )
    db.commit()


def test_decision_cannot_swap_the_candidates_assets(chain) -> None:
    db, ids = chain
    _candidate(db, ids, cid="c-swap")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _decision(db, ids, did="d-swap", cid="c-swap", current="b", related="a")


# --- attempt lease and projection ownership ---------------------------------


def _fingerprint(db, ids, digest, *, asset="a", version="v1", card=CARD_V1):
    """Every attempt names a fingerprint whose inputs are on record.

    Without the record the digest is a number nobody can re-derive, so a cached
    result could never be traced back to the model, prompt and configuration
    that produced it.
    """
    db.execute(
        "INSERT OR IGNORE INTO discovery_fingerprint_records("
        "discovery_fingerprint, fingerprint_schema_version, current_asset_id, "
        "current_version_id, current_knowledge_card_hash, current_projection_hash, "
        "eligible_projection_hashes_json, model_identity, model_revision, "
        "prompt_version, role_contract_version, validation_contract_version, "
        "discovery_intent_version, inference_parameters_hash, "
        "prefilter_config_version, created_at) "
        "VALUES (?, 'e5-fingerprint/v1', ?, ?, ?, ?, '[]', 'Qwen/Qwen2.5-14B-Instruct', "
        "'frozen', 'e5-discovery-prompt/v1', 'e5-role-graph/v1', 'e5-relation/v1', "
        "'e5-discovery-intent/v1', ?, 'e5-prefilter/v1', ?)",
        (
            digest,
            str(ids[asset]["asset"]),
            str(ids[asset][version]),
            card,
            "9" * 64,
            "8" * 64,
            NOW,
        ),
    )


def _attempt(
    db, ids, *, aid, asset="a", projection="proj-a-v1", outcome="RUNNING",
    lease=LATER, finished=None,
):
    _fingerprint(db, ids, aid, asset=asset)
    db.execute(
        "INSERT INTO relation_discovery_attempts(attempt_id, run_id, asset_id, "
        "discovery_fingerprint, current_projection_id, eligible_set_hash, "
        "attempt_number, outcome, lease_expires_at, started_at, finished_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
        (
            aid, str(uuid4()), str(ids[asset]["asset"]), aid, projection, "b" * 64,
            outcome, lease, NOW, finished,
        ),
    )


def test_attempt_positive_with_its_own_projection(chain) -> None:
    db, ids = chain
    _attempt(db, ids, aid="att-ok")
    db.commit()


def test_attempt_cannot_use_another_assets_projection(chain) -> None:
    db, ids = chain
    with pytest.raises(sqlite3.IntegrityError):
        _attempt(db, ids, aid="att-cross", asset="b", projection="proj-a-v1")


def test_running_attempt_requires_a_lease(chain) -> None:
    """A reservation with no expiry is invisible to recovery and blocks forever."""
    db, ids = chain
    with pytest.raises(sqlite3.IntegrityError):
        _attempt(db, ids, aid="att-nolease", lease=None)


def test_settled_attempt_must_release_its_lease(chain) -> None:
    """Otherwise recovery treats a finished attempt as still in flight."""
    db, ids = chain
    with pytest.raises(sqlite3.IntegrityError):
        _attempt(db, ids, aid="att-held", outcome="NO_MATCH", lease=LATER, finished=NOW)


# ---------------------------------------------------------------------------
# The five states the fourth review reached with a real SQLite probe. Each was
# accepted with `PRAGMA foreign_key_check` reporting zero violations, so the
# database considered them consistent while they described an authorization the
# user never gave.
# ---------------------------------------------------------------------------


def test_attempt_cannot_use_a_projection_the_candidate_did_not_use(chain) -> None:
    """Same fingerprint, other projection of the same asset.

    The cached result would then be attributed to a graph the candidate was not
    computed from, so a later identical search returns an answer explained by
    different content.
    """
    db, ids = chain
    _candidate(db, ids, cid="c-attproj")
    _fingerprint(db, ids, FINGERPRINT)
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO relation_discovery_attempts(attempt_id, run_id, asset_id, "
            "discovery_fingerprint, current_projection_id, eligible_set_hash, "
            "attempt_number, outcome, candidate_id, started_at, finished_at) "
            "VALUES ('att-proj', ?, ?, ?, 'proj-a-v2', ?, 1, 'CANDIDATE', "
            "'c-attproj', ?, ?)",
            (str(uuid4()), str(ids["a"]["asset"]), FINGERPRINT, "b" * 64, NOW, NOW),
        )


def test_confirmed_current_version_must_match_its_projection(chain) -> None:
    """A projection determines the version it was built from; they cannot differ."""
    db, ids = chain
    _candidate(db, ids, cid="c-cv")
    _decision(db, ids, did="d-cv", cid="c-cv")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _confirmed(db, ids, rid="r-cv", cid="c-cv", did="d-cv", current_version="v2")


def test_confirmed_related_version_must_match_its_projection(chain) -> None:
    db, ids = chain
    _candidate(db, ids, cid="c-rv")
    _decision(db, ids, did="d-rv", cid="c-rv")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _confirmed(db, ids, rid="r-rv", cid="c-rv", did="d-rv", related_version="v2")


def test_confirmed_cannot_carry_an_arbitrary_card_hash(chain) -> None:
    """Any 64 hex characters would otherwise pass as the card the user accepted."""
    db, ids = chain
    _candidate(db, ids, cid="c-card")
    _decision(db, ids, did="d-card", cid="c-card")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _confirmed(db, ids, rid="r-card", cid="c-card", did="d-card", card="f" * 64)


def test_a_decline_cannot_produce_a_confirmed_relation(chain) -> None:
    """The sharpest of the five: the user said no and access appears anyway.

    Proving only that the decision row exists is not enough — a DECLINE is a
    decision too. If ticket 07 later treats the confirmed ledger as the
    permission authority, this row grants exactly what the user refused.
    """
    db, ids = chain
    _candidate(db, ids, cid="c-decline")
    _decision(db, ids, did="d-decline", cid="c-decline", action="DECLINE")
    db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        _confirmed(db, ids, rid="r-decline", cid="c-decline", did="d-decline")


def test_a_confirm_decision_still_produces_a_relation(chain) -> None:
    """Paired positive: the rule above must not reject a legitimate confirmation."""
    db, ids = chain
    _candidate(db, ids, cid="c-yes")
    _decision(db, ids, did="d-yes", cid="c-yes", action="CONFIRM")
    _confirmed(db, ids, rid="r-yes", cid="c-yes", did="d-yes")
    db.commit()
