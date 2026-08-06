from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from colorgraph.agent.creative_contracts import (
    CardProvenance,
    CreativePossibilityCard,
    ProtectedAttribute,
    RetrievalRoute,
)
from colorgraph.agent.creative_corpus import (
    CreativeCorpusArtifactReference,
    CreativeCorpusAuthorizationEnvelope,
    CreativeCorpusSource,
    CreativeKnowledgeCorpus,
    load_creative_knowledge_corpus,
    sha256_file,
)
from colorgraph.cli import build_parser


def _artifact(root: Path, relative_path: str, content: str) -> CreativeCorpusArtifactReference:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return CreativeCorpusArtifactReference(
        relative_path=relative_path,
        sha256=sha256_file(path),
    )


def _source(root: Path, index: int) -> CreativeCorpusSource:
    source_id = f"source-{index}"
    source_snapshot = _artifact(
        root,
        f"sources/{source_id}.txt",
        f"Frozen source notes for {source_id}.",
    )
    rights_evidence = _artifact(
        root,
        f"rights/{source_id}.txt",
        f"Redistribution and creative retrieval approved for {source_id}.",
    )
    content_reviewed_by = [f"content-reviewer-{index}"]
    rights_reviewed_by = [f"rights-reviewer-{index}"]
    authorized_by = [f"authorization-owner-{index}"]
    reviewed_at = datetime(2026, 7, 30, 8, tzinfo=UTC)
    authorization = CreativeCorpusAuthorizationEnvelope(
        source_id=source_id,
        source_version="frozen-v1",
        source_snapshot_sha256=source_snapshot.sha256,
        rights_evidence_sha256=rights_evidence.sha256,
        permitted_uses=["creative_retrieval"],
        redistributable=True,
        content_reviewed_by=content_reviewed_by,
        rights_reviewed_by=rights_reviewed_by,
        authorized_by=authorized_by,
        reviewed_at=reviewed_at,
        authorized_at=reviewed_at,
        authorized=True,
    )
    return CreativeCorpusSource(
        source_id=source_id,
        title=f"Reviewed source {index}",
        source_uri=f"https://example.invalid/{source_id}",
        source_version="frozen-v1",
        rights="project-authorized-test",
        permitted_uses=["creative_retrieval"],
        redistributable=True,
        source_snapshot=source_snapshot,
        rights_evidence=rights_evidence,
        content_review_evidence=_artifact(
            root,
            f"reviews/{source_id}.txt",
            f"Content reviewed without scene-to-recipe shortcuts: {source_id}.",
        ),
        authorization_evidence=_artifact(
            root,
            f"authorizations/{source_id}.json",
            authorization.model_dump_json(indent=2),
        ),
        content_reviewed_by=content_reviewed_by,
        rights_reviewed_by=rights_reviewed_by,
        authorized_by=authorized_by,
        reviewed_at=reviewed_at,
        authorized_at=reviewed_at,
        authorized=True,
    )


def _card(
    source: CreativeCorpusSource,
    index: int,
    route: RetrievalRoute,
) -> CreativePossibilityCard:
    return CreativePossibilityCard(
        card_id=f"card-{index}",
        card_version="v1",
        provenance=CardProvenance(
            source_id=source.source_id,
            source_uri=source.source_uri,
            source_version=source.source_version,
            rights=source.rights,
            permitted_uses=source.permitted_uses,
            redistributable=source.redistributable,
        ),
        concept=f"Bounded visual possibility {index}",
        possible_visual_cues=[f"cue {index}", "preserve source evidence"],
        possible_grade_strategies=[
            f"strategy {index}",
            "test relationships without forcing a recipe",
        ],
        alternatives=[f"alternative {index}"],
        cliche_risks=[f"template shortcut {index}"],
        counterexamples=[f"counterexample {index}"],
        scene_terms=["landscape", f"scene-{index}"],
        emotion_terms=["restrained", f"mood-{index}"],
        route_support=[route],
        media_types=["video"],
        color_domains=["acescct"],
        scopes=["scene"],
        required_capabilities=[],
        compatible_protections=list(ProtectedAttribute),
        template_family=f"family-{index % 3}",
    )


def _write_corpus(root: Path) -> Path:
    sources = [_source(root, 0), _source(root, 1)]
    cards = [
        _card(
            sources[index % len(sources)],
            index,
            list(RetrievalRoute)[index % len(RetrievalRoute)],
        )
        for index in range(6)
    ]
    corpus = CreativeKnowledgeCorpus(
        corpus_id="creative-corpus-test",
        corpus_version="v1",
        created_at=datetime(2026, 7, 30, 8, tzinfo=UTC),
        sources=sources,
        cards=cards,
    )
    path = root / "creative-corpus.json"
    path.write_text(corpus.model_dump_json(indent=2), encoding="utf-8")
    return path


def test_authorized_content_bound_corpus_builds_a_retrieval_index(
    tmp_path: Path,
) -> None:
    path = _write_corpus(tmp_path)

    loaded = load_creative_knowledge_corpus(path)

    assert loaded.audit.passed
    assert loaded.audit.source_count == 2
    assert loaded.audit.card_count == 6
    assert loaded.audit.checked_authorization_artifacts == 2
    assert all(loaded.audit.retrieval_route_coverage.values())
    assert loaded.index is not None
    assert len(loaded.index.possibility_cards_for_retrieval()) == 6


def test_corpus_artifact_tampering_fails_closed(tmp_path: Path) -> None:
    path = _write_corpus(tmp_path)
    (tmp_path / "sources" / "source-0.txt").write_text(
        "tampered source",
        encoding="utf-8",
    )

    loaded = load_creative_knowledge_corpus(path)

    assert not loaded.audit.passed
    assert loaded.index is None
    assert any("digest mismatch" in issue for issue in loaded.audit.issues)


def test_card_provenance_must_match_its_reviewed_source(tmp_path: Path) -> None:
    path = _write_corpus(tmp_path)
    payload = CreativeKnowledgeCorpus.model_validate_json(
        path.read_text(encoding="utf-8")
    ).model_dump(mode="json")
    payload["cards"][0]["provenance"]["rights"] = "unreviewed-rights"

    with pytest.raises(ValidationError, match="provenance does not match"):
        CreativeKnowledgeCorpus.model_validate_json(json.dumps(payload))


def test_corpus_authorization_claims_are_recomputed_from_bound_evidence(
    tmp_path: Path,
) -> None:
    path = _write_corpus(tmp_path)
    payload = CreativeKnowledgeCorpus.model_validate_json(
        path.read_text(encoding="utf-8")
    ).model_dump(mode="json")
    payload["sources"][0]["authorized_by"] = ["unbound-authorizer"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_creative_knowledge_corpus(path)

    assert not loaded.audit.passed
    assert loaded.index is None
    assert any(
        "authorization claims do not match" in issue
        for issue in loaded.audit.issues
    )


def test_creative_corpus_audit_cli_writes_a_machine_readable_gate(
    tmp_path: Path,
) -> None:
    path = _write_corpus(tmp_path)
    output = tmp_path / "corpus-audit.json"
    arguments = build_parser().parse_args(
        [
            "creative-corpus-audit",
            "--input",
            str(path),
            "--output",
            str(output),
        ]
    )

    exit_code = arguments.handler(arguments)

    assert exit_code == 0
    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is True
