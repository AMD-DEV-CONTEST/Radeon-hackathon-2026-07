from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from creative_hub.db.models import TrialScriptRevisionRecord
from creative_hub.shidu.repository import IdempotencyConflict, ShiduRepository
from creative_hub.shidu.schemas import StoreTrialScript
from creative_hub.shidu.trial_methodology import TrialMethodologyService
from creative_hub.shidu.trial_script_compiler import (
    DeterministicTrialScriptTransport,
    TrialScriptCompiler,
)
from test_shidu_resonance import (
    PROJECT_ID,
    _proposal,
    _seed_publishable_pack,
    _service,
)
from test_shidu_trial_methodology import session


_DEFAULT = object()


class _RiskyTransport(DeterministicTrialScriptTransport):
    def generate_narration(self, request):
        payload = dict(super().generate_narration(request))
        payload["opening_line"] = "结局是" + payload["opening_line"]
        cues = [dict(item) for item in payload["narration_cues"]]
        cues[0]["text"] = "结局是" + cues[0]["text"]
        payload["narration_cues"] = cues
        return payload


def _seed_source_script(session: Session):
    repository, pack, claims = _seed_publishable_pack(session)
    direction = _service(repository, _proposal(claims)).publish(pack.id)[0]
    _, _, _, _, book_id = repository.load_direction_context(direction.id)
    methodology = TrialMethodologyService(repository).freeze(PROJECT_ID)
    safe_baseline = TrialScriptCompiler(repository=repository).compile(
        project_id=PROJECT_ID,
        book_id=book_id,
        direction_revision_id=direction.id,
        methodology_revision_id=methodology.id,
        command_key="script:safe-baseline",
    )
    source = TrialScriptCompiler(
        repository=repository, transport=_RiskyTransport()
    ).compile(
        project_id=PROJECT_ID,
        book_id=book_id,
        direction_revision_id=direction.id,
        methodology_revision_id=methodology.id,
        command_key="script:source",
    )
    assert source.payload["safety_gate"]["post_compile"][
        "blocked_reason_codes"
    ]
    return (
        repository,
        pack,
        claims,
        direction,
        methodology,
        source,
        safe_baseline.payload,
    )


def _source_safety_decision_digest(source) -> str:
    return source.payload["safety_gate"]["post_compile"][
        "release_decision_digest"
    ]


def _rewrite_payload(source, clean_payload, *, safety_digest=_DEFAULT):
    payload = deepcopy(clean_payload)
    if safety_digest is _DEFAULT:
        safety_digest = _source_safety_decision_digest(source)
    payload["safety_rewrite_provenance"] = {
        "source_trial_script_revision_id": str(source.id),
        "source_trial_script_digest": source.digest,
        "source_safety_decision_digest": safety_digest,
    }
    return payload


def _rewrite_command(
    source,
    clean_payload,
    *,
    payload=None,
    command_key: str = "script:rewrite",
    direction_id=None,
    source_id=None,
    safety_digest=_DEFAULT,
):
    resolved_safety_digest = (
        _source_safety_decision_digest(source)
        if safety_digest is _DEFAULT
        else safety_digest
    )
    return StoreTrialScript(
        project_id=source.project_id,
        book_id=source.book_id,
        evidence_pack_revision_id=source.evidence_pack_revision_id,
        resonance_direction_revision_id=(
            direction_id or source.resonance_direction_revision_id
        ),
        methodology_revision_id=source.methodology_revision_id,
        payload=(
            payload
            if payload is not None
            else _rewrite_payload(
                source,
                clean_payload,
                safety_digest=(
                    _source_safety_decision_digest(source)
                    if resolved_safety_digest is None
                    else resolved_safety_digest
                ),
            )
        ),
        command_key=command_key,
        source_trial_script_revision_id=(
            source.id if source_id is None else source_id
        ),
        source_safety_decision_digest=resolved_safety_digest,
    )


def test_store_safety_rewrite_creates_immutable_revision_and_replays(
    session: Session,
) -> None:
    repository, _, _, _, _, source, clean_payload = _seed_source_script(
        session
    )
    source_payload = deepcopy(source.payload)

    rewrite = repository.store_trial_script(
        _rewrite_command(source, clean_payload)
    )

    assert rewrite.id != source.id
    assert rewrite.revision == source.revision + 1
    assert rewrite.source_trial_script_revision_id == source.id
    assert rewrite.source_safety_decision_digest == (
        _source_safety_decision_digest(source)
    )
    assert repository.get_trial_script(source.id).payload == source_payload
    assert repository.store_trial_script(
        _rewrite_command(source, clean_payload)
    ).id == rewrite.id


def test_safety_rewrite_lineage_is_paired_and_payload_bound(
    session: Session,
) -> None:
    repository, _, _, _, _, source, clean_payload = _seed_source_script(
        session
    )

    with pytest.raises(ValueError, match="paired"):
        repository.store_trial_script(
            _rewrite_command(
                source,
                clean_payload,
                safety_digest=None,
                command_key="rewrite:unpaired",
            )
        )

    with pytest.raises(ValueError, match="provenance"):
        repository.store_trial_script(
            StoreTrialScript(
                project_id=source.project_id,
                book_id=source.book_id,
                evidence_pack_revision_id=source.evidence_pack_revision_id,
                resonance_direction_revision_id=(
                    source.resonance_direction_revision_id
                ),
                methodology_revision_id=source.methodology_revision_id,
                payload=_rewrite_payload(source, clean_payload),
                command_key="rewrite:payload-only",
            )
        )

    forged_payload = _rewrite_payload(source, clean_payload)
    forged_payload["safety_rewrite_provenance"][
        "source_trial_script_digest"
    ] = "b" * 64
    with pytest.raises(ValueError, match="provenance"):
        repository.store_trial_script(
            _rewrite_command(
                source,
                clean_payload,
                payload=forged_payload,
                command_key="rewrite:forged-source-digest",
            )
        )

    forged_decision = "c" * 64
    with pytest.raises(ValueError, match="decision digest is not exact"):
        repository.store_trial_script(
            _rewrite_command(
                source,
                clean_payload,
                payload=_rewrite_payload(
                    source,
                    clean_payload,
                    safety_digest=forged_decision,
                ),
                safety_digest=forged_decision,
                command_key="rewrite:forged-safety-decision",
            )
        )

    safe_record = session.scalar(
        select(TrialScriptRevisionRecord).where(
            TrialScriptRevisionRecord.project_id == source.project_id,
            TrialScriptRevisionRecord.book_id == source.book_id,
            TrialScriptRevisionRecord.revision == 1,
        )
    )
    assert safe_record is not None
    safe_source = repository.get_trial_script(safe_record.id)
    with pytest.raises(ValueError, match="does not authorize"):
        repository.store_trial_script(
            _rewrite_command(
                safe_source,
                clean_payload,
                command_key="rewrite:safe-source",
            )
        )


def test_safety_rewrite_command_idempotency_includes_lineage(
    session: Session,
) -> None:
    (
        repository,
        _,
        _,
        direction,
        methodology,
        source,
        clean_payload,
    ) = _seed_source_script(session)
    repository.store_trial_script(_rewrite_command(source, clean_payload))
    alternate_source = TrialScriptCompiler(
        repository=repository, transport=_RiskyTransport()
    ).compile(
        project_id=PROJECT_ID,
        book_id=source.book_id,
        direction_revision_id=direction.id,
        methodology_revision_id=methodology.id,
        command_key="script:alternate-source",
    )

    with pytest.raises(IdempotencyConflict, match="different content"):
        repository.store_trial_script(
            _rewrite_command(
                alternate_source,
                clean_payload,
            )
        )


def test_safety_rewrite_rejects_source_from_different_direction(
    session: Session,
) -> None:
    repository, pack, claims, direction, methodology, source, clean_payload = (
        _seed_source_script(session)
    )
    other_direction = _service(
        repository,
        _proposal(claims, key="other-door", title="另一扇门"),
        prompt_version="resonance-prompt-v1-other",
    ).publish(pack.id)[0]
    other_source = TrialScriptCompiler(
        repository=repository, transport=_RiskyTransport()
    ).compile(
        project_id=PROJECT_ID,
        book_id=source.book_id,
        direction_revision_id=other_direction.id,
        methodology_revision_id=methodology.id,
        command_key="script:other-source",
    )
    payload = deepcopy(clean_payload)
    payload["safety_rewrite_provenance"] = {
        "source_trial_script_revision_id": str(other_source.id),
        "source_trial_script_digest": other_source.digest,
        "source_safety_decision_digest": (
            _source_safety_decision_digest(other_source)
        ),
    }

    with pytest.raises(ValueError, match="same frozen context"):
        repository.store_trial_script(
            _rewrite_command(
                source,
                clean_payload,
                payload=payload,
                command_key="rewrite:cross-direction",
                direction_id=direction.id,
                source_id=other_source.id,
            )
        )


def test_reload_fails_closed_for_tampered_or_self_rewrite_lineage(
    session: Session,
) -> None:
    repository, _, _, _, _, source, clean_payload = _seed_source_script(
        session
    )
    rewrite = repository.store_trial_script(
        _rewrite_command(source, clean_payload)
    )

    session.execute(
        update(TrialScriptRevisionRecord)
        .where(TrialScriptRevisionRecord.id == rewrite.id)
        .values(source_safety_decision_digest="d" * 64)
    )
    session.expire_all()
    with pytest.raises(ValueError, match="provenance"):
        repository.get_trial_script(rewrite.id)

    session.execute(
        update(TrialScriptRevisionRecord)
        .where(TrialScriptRevisionRecord.id == rewrite.id)
        .values(
            source_safety_decision_digest=(
                _source_safety_decision_digest(source)
            )
        )
    )
    savepoint = session.begin_nested()
    try:
        with pytest.raises(IntegrityError):
            session.execute(
                update(TrialScriptRevisionRecord)
                .where(TrialScriptRevisionRecord.id == rewrite.id)
                .values(source_trial_script_revision_id=rewrite.id)
            )
    finally:
        savepoint.rollback()

    session.expire_all()
    record = session.get(TrialScriptRevisionRecord, rewrite.id)
    assert record is not None
    record.source_trial_script_revision_id = rewrite.id
    with session.no_autoflush, pytest.raises(ValueError, match="itself"):
        repository.get_trial_script(rewrite.id)


def test_trial_script_table_has_durable_rewrite_lineage_constraints() -> None:
    table = TrialScriptRevisionRecord.__table__
    assert {
        "source_trial_script_revision_id",
        "source_safety_decision_digest",
    } <= set(table.columns.keys())
    names = {constraint.name for constraint in table.constraints}
    assert "fk_orch_trial_scripts_source" in names
    assert "ck_orch_trial_scripts_source_pair" in names
    assert "ck_orch_trial_scripts_source_not_self" in names
    assert "ck_orch_trial_scripts_source_safety_digest" in names
