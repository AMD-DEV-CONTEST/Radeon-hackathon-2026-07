from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from colorgraph.agent.creative_contracts import (
    CreativePossibilityCard,
    Identifier,
    NonEmptyString,
    RetrievalRoute,
    Sha256,
    StrictFrozenModel,
)
from colorgraph.agent.creative_retrieval import CreativeKnowledgeIndex

CREATIVE_CORPUS_VERSION = "colorgraph.creative-knowledge-corpus/v1"
CREATIVE_CORPUS_AUDIT_VERSION = "colorgraph.creative-corpus-audit/v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CreativeCorpusArtifactReference(StrictFrozenModel):
    relative_path: NonEmptyString
    sha256: Sha256

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("creative corpus paths must be relative and contained")
        return value


class CreativeCorpusSource(StrictFrozenModel):
    source_id: Identifier
    title: NonEmptyString
    source_uri: NonEmptyString
    source_version: Identifier
    rights: NonEmptyString
    permitted_uses: list[Identifier] = Field(min_length=1)
    redistributable: bool
    source_snapshot: CreativeCorpusArtifactReference
    rights_evidence: CreativeCorpusArtifactReference
    content_review_evidence: CreativeCorpusArtifactReference
    authorization_evidence: CreativeCorpusArtifactReference
    content_reviewed_by: list[Identifier] = Field(min_length=1)
    rights_reviewed_by: list[Identifier] = Field(min_length=1)
    authorized_by: list[Identifier] = Field(min_length=1)
    reviewed_at: datetime
    authorized_at: datetime
    authorized: bool

    @model_validator(mode="after")
    def validate_retrieval_rights(self) -> CreativeCorpusSource:
        if "creative_retrieval" not in self.permitted_uses:
            raise ValueError("creative corpus sources must permit creative_retrieval")
        if not self.redistributable:
            raise ValueError(
                "publishable creative corpus sources must be redistributable"
            )
        if len(self.content_reviewed_by) != len(set(self.content_reviewed_by)):
            raise ValueError("creative corpus content reviewers must be unique")
        if len(self.rights_reviewed_by) != len(set(self.rights_reviewed_by)):
            raise ValueError("creative corpus rights reviewers must be unique")
        if len(self.authorized_by) != len(set(self.authorized_by)):
            raise ValueError("creative corpus authorizers must be unique")
        if set(self.content_reviewed_by) & set(self.rights_reviewed_by):
            raise ValueError(
                "creative corpus content and rights review must be independent"
            )
        return self


class CreativeCorpusAuthorizationEnvelope(StrictFrozenModel):
    schema_version: Literal[
        "colorgraph.creative-corpus-authorization/v1"
    ] = "colorgraph.creative-corpus-authorization/v1"
    source_id: Identifier
    source_version: Identifier
    source_snapshot_sha256: Sha256
    rights_evidence_sha256: Sha256
    permitted_uses: list[Identifier] = Field(min_length=1)
    redistributable: bool
    content_reviewed_by: list[Identifier] = Field(min_length=1)
    rights_reviewed_by: list[Identifier] = Field(min_length=1)
    authorized_by: list[Identifier] = Field(min_length=1)
    reviewed_at: datetime
    authorized_at: datetime
    authorized: bool


class CreativeKnowledgeCorpus(StrictFrozenModel):
    schema_version: Literal["colorgraph.creative-knowledge-corpus/v1"] = (
        CREATIVE_CORPUS_VERSION
    )
    corpus_id: Identifier
    corpus_version: Identifier
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    minimum_sources: int = Field(default=2, ge=1)
    minimum_cards: int = Field(default=6, ge=1)
    maximum_template_family_share: float = Field(default=0.5, ge=0, le=1)
    sources: list[CreativeCorpusSource] = Field(min_length=1)
    cards: list[CreativePossibilityCard] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source_and_card_bindings(self) -> CreativeKnowledgeCorpus:
        sources = {source.source_id: source for source in self.sources}
        if len(sources) != len(self.sources):
            raise ValueError("creative corpus source IDs must be unique")
        card_ids = [card.card_id for card in self.cards]
        if len(card_ids) != len(set(card_ids)):
            raise ValueError("creative corpus card IDs must be unique")
        for card in self.cards:
            source = sources.get(card.provenance.source_id)
            if source is None:
                raise ValueError(
                    f"creative card {card.card_id!r} references an unknown source"
                )
            expected = {
                "source_uri": source.source_uri,
                "source_version": source.source_version,
                "rights": source.rights,
                "permitted_uses": source.permitted_uses,
                "redistributable": source.redistributable,
            }
            actual = card.provenance.model_dump(
                mode="json",
                exclude={"source_id"},
            )
            if actual != expected:
                raise ValueError(
                    f"creative card {card.card_id!r} provenance does not match "
                    f"source {source.source_id!r}"
                )
        return self


class CreativeCorpusAuditReport(StrictFrozenModel):
    schema_version: Literal["colorgraph.creative-corpus-audit/v1"] = (
        CREATIVE_CORPUS_AUDIT_VERSION
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    corpus_id: Identifier
    corpus_version: Identifier
    corpus_sha256: Sha256
    source_count: int = Field(ge=0)
    card_count: int = Field(ge=0)
    checked_source_artifacts: int = Field(ge=0)
    checked_rights_artifacts: int = Field(ge=0)
    checked_content_review_artifacts: int = Field(ge=0)
    checked_authorization_artifacts: int = Field(ge=0)
    retrieval_route_coverage: dict[RetrievalRoute, bool]
    maximum_template_family_share: float = Field(ge=0, le=1)
    issues: list[NonEmptyString]
    passed: bool


@dataclass(frozen=True, slots=True)
class LoadedCreativeKnowledgeCorpus:
    corpus: CreativeKnowledgeCorpus
    audit: CreativeCorpusAuditReport
    index: CreativeKnowledgeIndex | None


def _resolve_artifact(
    root: Path,
    reference: CreativeCorpusArtifactReference,
) -> Path:
    path = (root / reference.relative_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(
            f"creative corpus path escapes its root: {reference.relative_path!r}"
        )
    return path


def _check_artifact(
    root: Path,
    reference: CreativeCorpusArtifactReference,
    *,
    label: str,
    issues: list[str],
) -> bool:
    try:
        path = _resolve_artifact(root, reference)
    except ValueError as exc:
        issues.append(str(exc))
        return False
    if not path.is_file():
        issues.append(f"{label} is missing: {reference.relative_path}")
        return False
    actual = sha256_file(path)
    if actual != reference.sha256:
        issues.append(
            f"{label} digest mismatch: expected {reference.sha256}, got {actual}"
        )
        return False
    return True


def audit_creative_knowledge_corpus(
    corpus: CreativeKnowledgeCorpus,
    *,
    corpus_path: Path,
    expected_sha256: str | None = None,
) -> CreativeCorpusAuditReport:
    corpus_path = corpus_path.resolve()
    corpus_sha256 = sha256_file(corpus_path)
    root = corpus_path.parent.resolve()
    issues: list[str] = []
    if expected_sha256 is not None and corpus_sha256 != expected_sha256:
        issues.append(
            "creative corpus digest mismatch: "
            f"expected {expected_sha256}, got {corpus_sha256}"
        )
    if len(corpus.sources) < corpus.minimum_sources:
        issues.append(
            f"creative corpus has {len(corpus.sources)} sources; "
            f"{corpus.minimum_sources} required"
        )
    if len(corpus.cards) < corpus.minimum_cards:
        issues.append(
            f"creative corpus has {len(corpus.cards)} cards; "
            f"{corpus.minimum_cards} required"
        )
    unauthorized = sorted(
        source.source_id for source in corpus.sources if not source.authorized
    )
    if unauthorized:
        issues.append(f"creative corpus has unauthorized sources: {unauthorized}")

    checked_sources = 0
    checked_rights = 0
    checked_content_reviews = 0
    checked_authorizations = 0
    for source in corpus.sources:
        if _check_artifact(
            root,
            source.source_snapshot,
            label=f"{source.source_id} source snapshot",
            issues=issues,
        ):
            checked_sources += 1
        if _check_artifact(
            root,
            source.rights_evidence,
            label=f"{source.source_id} rights evidence",
            issues=issues,
        ):
            checked_rights += 1
        if _check_artifact(
            root,
            source.content_review_evidence,
            label=f"{source.source_id} content review evidence",
            issues=issues,
        ):
            checked_content_reviews += 1
        if _check_artifact(
            root,
            source.authorization_evidence,
            label=f"{source.source_id} authorization evidence",
            issues=issues,
        ):
            authorization_path = _resolve_artifact(
                root,
                source.authorization_evidence,
            )
            try:
                authorization = (
                    CreativeCorpusAuthorizationEnvelope.model_validate_json(
                        authorization_path.read_text(encoding="utf-8")
                    )
                )
            except (OSError, ValueError) as exc:
                issues.append(
                    f"{source.source_id} authorization evidence is invalid: {exc}"
                )
            else:
                checked_authorizations += 1
                expected = CreativeCorpusAuthorizationEnvelope(
                    source_id=source.source_id,
                    source_version=source.source_version,
                    source_snapshot_sha256=source.source_snapshot.sha256,
                    rights_evidence_sha256=source.rights_evidence.sha256,
                    permitted_uses=source.permitted_uses,
                    redistributable=source.redistributable,
                    content_reviewed_by=source.content_reviewed_by,
                    rights_reviewed_by=source.rights_reviewed_by,
                    authorized_by=source.authorized_by,
                    reviewed_at=source.reviewed_at,
                    authorized_at=source.authorized_at,
                    authorized=source.authorized,
                )
                if authorization != expected:
                    issues.append(
                        f"{source.source_id} authorization claims do not "
                        "match the corpus"
                    )

    route_coverage = {
        route: any(route in card.route_support for card in corpus.cards)
        for route in RetrievalRoute
    }
    missing_routes = [
        route.value for route, covered in route_coverage.items() if not covered
    ]
    if missing_routes:
        issues.append(f"creative corpus does not cover retrieval routes: {missing_routes}")

    template_counts = Counter(card.template_family for card in corpus.cards)
    maximum_template_share = (
        max(template_counts.values()) / len(corpus.cards) if corpus.cards else 1
    )
    if maximum_template_share > corpus.maximum_template_family_share:
        issues.append(
            "creative corpus template-family concentration exceeds "
            f"{corpus.maximum_template_family_share:.3f}: "
            f"{maximum_template_share:.3f}"
        )

    passed = not issues
    return CreativeCorpusAuditReport(
        corpus_id=corpus.corpus_id,
        corpus_version=corpus.corpus_version,
        corpus_sha256=corpus_sha256,
        source_count=len(corpus.sources),
        card_count=len(corpus.cards),
        checked_source_artifacts=checked_sources,
        checked_rights_artifacts=checked_rights,
        checked_content_review_artifacts=checked_content_reviews,
        checked_authorization_artifacts=checked_authorizations,
        retrieval_route_coverage=route_coverage,
        maximum_template_family_share=maximum_template_share,
        issues=issues,
        passed=passed,
    )


def load_creative_knowledge_corpus(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
) -> LoadedCreativeKnowledgeCorpus:
    corpus_path = Path(path).resolve()
    corpus = CreativeKnowledgeCorpus.model_validate_json(
        corpus_path.read_text(encoding="utf-8")
    )
    audit = audit_creative_knowledge_corpus(
        corpus,
        corpus_path=corpus_path,
        expected_sha256=expected_sha256,
    )
    index = None
    if audit.passed:
        index = CreativeKnowledgeIndex(
            f"{corpus.corpus_id}:{corpus.corpus_version}"
        )
        for card in corpus.cards:
            index.publish_possibility(card)
    return LoadedCreativeKnowledgeCorpus(
        corpus=corpus,
        audit=audit,
        index=index,
    )
