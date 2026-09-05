"""The product path emits into the frozen retrieval-phase trace.

Closes ticket 03 criterion 9, ticket 04 criterion 10 and ticket 08 criterion 8.

The oracle is `qa/scripts/check_retrieval_phase.py`, imported and run against
the trace these operations actually produce. Asserting field-by-field here
instead would test my reading of the invariants rather than the invariants, and
the checker already encodes them: readiness before any cross-asset search, a
confirmation before any detail read, hashes equal across a historical read.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.experience_asset.api.main import create_app
from app.experience_asset.application.relation_evidence import (
    EvidenceCardV1,
    read_evidence_card_traced,
)
from app.experience_asset.domain.enums import RelationLifecycle
from app.experience_asset.domain.relation import ConfirmedAssetRelationV1
from tests.integration.test_m4_api import ScriptedM4Client, create_m4
from tests.integration.test_m4_readiness import _accept, _discovery_body

ROOT = Path(__file__).resolve().parents[2]


def _checker():
    """Import the real QA checker rather than reimplementing its rules."""
    spec = importlib.util.spec_from_file_location(
        "check_retrieval_phase", ROOT / "qa" / "scripts" / "check_retrieval_phase.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = _checker()


def _trace(client: TestClient, asset_id: str) -> dict:
    return client.app.state.repository.read_retrieval_trace(asset_id)


def _blocking(findings) -> list:
    return [item for item in findings if item[0] in {"CRITICAL", "HIGH"}]


def _client(tmp_path: Path, name: str) -> TestClient:
    return TestClient(
        create_app(database_path=tmp_path / name, model_client=ScriptedM4Client())
    )


def test_the_trace_shape_matches_the_frozen_contract(tmp_path: Path):
    with _client(tmp_path, "shape.sqlite3") as client:
        asset_id, workspace = create_m4(client)
        _accept(client, asset_id, workspace)

        trace = _trace(client, asset_id)

    assert trace["schema_version"] == "retrieval-phase-trace/v1"
    assert trace["asset_id"] == asset_id
    assert trace["events"], "acceptance must leave a record"
    # Same document shape the E2 capture script emits and the frontend consumes.
    assert set(trace) == {"schema_version", "asset_id", "events"}
    assert json.loads(json.dumps(trace)) == trace


def test_acceptance_records_readiness_bindings_and_the_projection(tmp_path: Path):
    """Ticket 03 criterion 9 and ticket 04 criterion 10."""
    with _client(tmp_path, "ready.sqlite3") as client:
        asset_id, workspace = create_m4(client)
        record = _accept(client, asset_id, workspace).json()

        trace = _trace(client, asset_id)

    ready = [e for e in trace["events"] if e["event_type"] == "knowledge_card_ready"]
    assert len(ready) == 1
    event = ready[0]
    assert event["knowledge_card_version"] == record["version_id"]
    assert event["knowledge_card_hash"] == record["knowledge_card_hash"]
    assert event["milestone_state"] == record["milestone_state"]
    assert event["explicit_user_acceptance"] is True
    # 04/10: projection and index state observable at an external seam. The
    # projection activates in the same action, so it rides this event rather
    # than needing a type the frozen vocabulary does not have.
    assert event["projection_id"] and event["projection_hash"]
    assert not _blocking(CHECKER.check(trace))


def test_a_denied_search_records_its_reason_without_claiming_a_retrieval(tmp_path: Path):
    """Ticket 03 criterion 9's second half."""
    with _client(tmp_path, "denied.sqlite3") as client:
        asset_id, workspace = create_m4(client)

        denied = client.post(
            f"/api/v1/relations/assets/{asset_id}/discovery",
            json=_discovery_body(asset_id, workspace),
        )
        assert denied.status_code == 409

        trace = _trace(client, asset_id)

    search = [e for e in trace["events"] if e["event_type"] == "relation_candidate_search"]
    assert len(search) == 1
    assert search[0]["denied"] is True
    assert search[0]["denial_reason"] == "NOT_READY"
    # Nothing was read, so nothing may be named.
    assert "related_asset_id" not in search[0]
    # And the checker must not read it as a search that ran before readiness —
    # that finding would be CRITICAL and describe the opposite of what happened.
    assert not _blocking(CHECKER.check(trace))


def test_a_denied_search_before_readiness_is_still_ordered_before_it(tmp_path: Path):
    with _client(tmp_path, "order.sqlite3") as client:
        asset_id, workspace = create_m4(client)
        client.post(
            f"/api/v1/relations/assets/{asset_id}/discovery",
            json=_discovery_body(asset_id, workspace),
        )
        _accept(client, asset_id, workspace)

        trace = _trace(client, asset_id)

    types = [e["event_type"] for e in trace["events"]]
    assert types == ["relation_candidate_search", "knowledge_card_ready"]
    sequences = [e["sequence"] for e in trace["events"]]
    assert sequences == sorted(set(sequences)) == [0, 1]
    assert not _blocking(CHECKER.check(trace))


def test_a_finished_search_that_found_nothing_is_on_the_record(tmp_path: Path):
    with _client(tmp_path, "nomatch.sqlite3") as client:
        asset_id, workspace = create_m4(client)
        record = _accept(client, asset_id, workspace).json()

        started = client.post(
            f"/api/v1/relations/assets/{asset_id}/discovery",
            json=_discovery_body(asset_id, workspace, record),
        )
        assert started.status_code == 202
        assert started.json()["discovery_outcome"] == "NO_MATCH"

        trace = _trace(client, asset_id)

    # An abstention that left no record would be indistinguishable from never
    # having looked.
    assert [e["event_type"] for e in trace["events"]] == [
        "knowledge_card_ready",
        "relation_no_match",
    ]
    assert not _blocking(CHECKER.check(trace))


def test_a_pre_readiness_search_is_rejected_by_the_checker_when_not_denied(tmp_path: Path):
    """The negative pair: the denial exemption must not disarm the rule."""
    forged = {
        "schema_version": "retrieval-phase-trace/v1",
        "asset_id": str(uuid4()),
        "events": [
            {
                "sequence": 0,
                "event_type": "relation_candidate_search",
                "scope": "cross_asset_summary",
                "detail_included": False,
                "related_asset_id": str(uuid4()),
            }
        ],
    }

    findings = CHECKER.check(forged)

    assert any(
        "before Knowledge Card readiness" in message for _, _, message in findings
    )
    # And a denied event that names a target is still refused, so the exemption
    # cannot be used to smuggle a cross-asset reference through.
    smuggled = json.loads(json.dumps(forged))
    smuggled["events"][0]["denied"] = True
    smuggled["events"][0]["denial_reason"] = "NOT_READY"
    assert any(
        "must not name a cross-asset target" in message
        for _, _, message in CHECKER.check(smuggled)
    )


def test_the_bounded_detail_read_records_its_provenance_and_hashes(tmp_path: Path):
    """Ticket 08 criterion 8, at the module seam the HTTP handler will call."""
    from app.experience_asset.application.decision import DecisionService
    from tests.integration.test_e5_decision import (
        _decision,
        _pair,
        _settled_candidate,
    )

    repository, current, historical = _pair(tmp_path, "detail.sqlite3")
    candidate = _settled_candidate(repository, current, historical)
    asset, readiness, projection = current
    DecisionService(repository).decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, "CONFIRM")
    )
    relation = repository.list_confirmed_relations(asset.asset_id)[0]
    historical_projection = next(
        item
        for item in repository.list_eligible_projections(current_asset_id=uuid4())
        if item.projection_id == candidate.historical_projection_id
    )

    card = read_evidence_card_traced(
        repository,
        relation=relation,
        candidate=repository.read_candidate(candidate.candidate_id),
        current_projection=projection,
        historical_projection=historical_projection,
    )

    assert isinstance(card, EvidenceCardV1), card
    detail = [
        e
        for e in repository.read_retrieval_trace(asset.asset_id)["events"]
        if e["event_type"] == "relation_detail_retrieval"
    ]
    assert len(detail) == 1
    event = detail[0]
    assert event["scope"] == "cross_asset_detail"
    assert event["provenance_refs"]
    assert event["mutated_current_statements"] is False
    # Two hashes rather than one boolean: a boolean is the emitter's claim about
    # itself, two hashes are a fact the checker compares.
    assert (
        event["current_statements_hash_before"]
        == event["current_statements_hash_after"]
    )
    assert event["knowledge_card_version"] == str(relation.current_version_id)


def test_a_refused_card_records_no_detail_access(tmp_path: Path):
    from tests.integration.test_e5_decision import _pair, _settled_candidate

    repository, current, historical = _pair(tmp_path, "refused.sqlite3")
    candidate = _settled_candidate(repository, current, historical)
    asset, _, projection = current
    historical_projection = next(
        item
        for item in repository.list_eligible_projections(current_asset_id=uuid4())
        if item.projection_id == candidate.historical_projection_id
    )
    invalidated = ConfirmedAssetRelationV1(
        relation_id=uuid4(),
        source_candidate_id=candidate.candidate_id,
        relation_type=candidate.relation_type,
        current_asset_id=candidate.current_asset_id,
        current_version_id=asset.version_id,
        current_projection_id=candidate.current_projection_id,
        current_knowledge_card_hash="a" * 64,
        related_asset_id=candidate.related_asset_id,
        related_version_id=uuid4(),
        historical_projection_id=candidate.historical_projection_id,
        lifecycle=RelationLifecycle.INVALIDATED,
        confirmed_at=datetime.now(UTC),
        invalidated_at=datetime.now(UTC),
        invalidation_reason="probe",
    )

    result = read_evidence_card_traced(
        repository,
        relation=invalidated,
        candidate=repository.read_candidate(candidate.candidate_id),
        current_projection=projection,
        historical_projection=historical_projection,
    )

    assert not isinstance(result, EvidenceCardV1)
    # Logging a read the gate refused would put a cross_asset_detail event on
    # the record for an access that never happened, and the checker would then
    # be validating a fiction.
    assert not [
        e
        for e in repository.read_retrieval_trace(asset.asset_id)["events"]
        if e["event_type"] == "relation_detail_retrieval"
    ]


@pytest.mark.parametrize("decision", ["CONFIRM", "DECLINE"])
def test_both_decisions_reach_the_trace(tmp_path: Path, decision: str):
    from app.experience_asset.application.decision import DecisionService
    from tests.integration.test_e5_decision import (
        _decision,
        _pair,
        _settled_candidate,
    )

    repository, current, historical = _pair(tmp_path, f"decide-{decision}.sqlite3")
    candidate = _settled_candidate(repository, current, historical)
    asset, readiness, _ = current

    DecisionService(repository).decide(
        asset.asset_id, candidate.candidate_id, _decision(candidate, readiness, decision)
    )

    events = [
        e
        for e in repository.read_retrieval_trace(asset.asset_id)["events"]
        if e["event_type"] == "relation_confirmation"
    ]
    assert len(events) == 1
    # A trace that logged only confirmations could not show that a refusal was
    # ever answered.
    assert events[0]["confirmed"] is (decision == "CONFIRM")
    assert events[0]["related_asset_id"] == str(candidate.related_asset_id)
