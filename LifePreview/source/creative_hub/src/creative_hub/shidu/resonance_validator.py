"""Deterministic resonance scoring and evidence-bound publication gates."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.shidu.schemas import (
    EvidenceClaim,
    EvidencePackRevision,
    SourceDocumentRevision,
)


DIRECTION_SCORE_VERSION = "shidu-direction-score-v1"
DIRECTION_SCHEMA_VERSION = "shidu-resonance-direction-v1"
RESONANCE_VALIDATOR_VERSION = "shidu-resonance-validator-v1"
CLUSTER_SCHEMA_VERSION = "shidu-resonance-cluster-v1"
CLUSTERING_VERSION = "shidu-resonance-clustering-v1"
PENALTY_VERSION = "shidu-resonance-penalties-v1"
POLICY_VERSION = "shidu-resonance-policy-v1"

_SPOILER_ORDER = {"none": 0, "light": 1, "moderate": 2, "critical": 3}
_SPOILER_PENALTY = {"none": 0.0, "light": 0.02, "moderate": 0.15, "critical": 0.35}
_SOURCE_RELIABILITY = {
    "ai_generated": 0.25,
    "official": 1.0,
    "academic": 0.95,
    "publisher": 0.95,
    "reference": 0.90,
    "interview": 0.85,
    "review": 0.75,
    "media": 0.75,
    "article": 0.70,
    "community": 0.60,
    "web": 0.60,
    "unknown": 0.50,
}
_POV_FORBIDDEN = (
    "多年后",
    "后来我才知道",
    "结局",
    "最终我会",
    "此时我不知道",
    "未来的我",
)

GAP_CODE_ORDER = (
    "critical_conflict_unresolved",
    "pack_not_publishable",
    "model_contract_invalid",
    "duplicate_cluster",
    "duplicate_evidence_id",
    "foreign_evidence_id",
    "evidence_lineage_mismatch",
    "independent_sources_insufficient",
    "source_types_insufficient",
    "plot_node_missing",
    "emotional_reaction_missing",
    "reader_fit_missing",
    "spoiler_metadata_mismatch",
    "spoiler_policy_exceeded",
    "pov_entry_not_grounded",
    "fit_for_missing",
    "not_fit_for_missing",
    "ungrounded_statement",
    "unverified_direct_quote",
    "copyright_risk",
    "score_payload_invalid",
)
_GAP_RANK = {code: index for index, code in enumerate(GAP_CODE_ORDER)}


class ResonanceValidationError(ValueError):
    """The model proposal or persisted direction violated the frozen contract."""


@dataclass(frozen=True)
class GroundedText:
    text: str
    evidence_ids: tuple[UUID, ...]
    kind: Literal["paraphrase", "verified_quote"] = "paraphrase"

    def model_dump(self, *, mode: str = "python") -> dict[str, object]:
        ids: list[object]
        if mode == "json":
            ids = [str(item) for item in self.evidence_ids]
        else:
            ids = list(self.evidence_ids)
        return {"text": self.text, "evidence_ids": ids, "kind": self.kind}


@dataclass(frozen=True)
class ClusterProposal:
    cluster_key: str
    evidence_ids: tuple[UUID, ...]
    title: str
    factual_statements: tuple[GroundedText, ...]
    first_person_entry: GroundedText
    perceived_detail: GroundedText
    fit_for: tuple[GroundedText, ...]
    not_fit_for: tuple[GroundedText, ...]
    spoiler_level: Literal["none", "light", "moderate", "critical"]

    def model_dump(self, *, mode: str = "python") -> dict[str, object]:
        evidence_ids: list[object]
        if mode == "json":
            evidence_ids = [str(item) for item in self.evidence_ids]
        else:
            evidence_ids = list(self.evidence_ids)
        return {
            "cluster_key": self.cluster_key,
            "evidence_ids": evidence_ids,
            "title": self.title,
            "factual_statements": [
                item.model_dump(mode=mode) for item in self.factual_statements
            ],
            "first_person_entry": self.first_person_entry.model_dump(mode=mode),
            "perceived_detail": self.perceived_detail.model_dump(mode=mode),
            "fit_for": [item.model_dump(mode=mode) for item in self.fit_for],
            "not_fit_for": [
                item.model_dump(mode=mode) for item in self.not_fit_for
            ],
            "spoiler_level": self.spoiler_level,
        }


@dataclass(frozen=True)
class DirectionSignals:
    cross_source_repetition: float
    independent_source_diversity: float
    emotion_specificity: float
    experiential_cinematic_fit: float
    interaction_signal: float | None
    source_reliability: float


@dataclass(frozen=True)
class DirectionPenalties:
    spoiler: float = 0.0
    copyright: float = 0.0
    conflict: float = 0.0
    version: str = PENALTY_VERSION


@dataclass(frozen=True)
class ResonancePolicy:
    max_spoiler_level: Literal["none", "light", "moderate", "critical"] = "light"
    version: str = POLICY_VERSION

    def __post_init__(self) -> None:
        if self.max_spoiler_level not in _SPOILER_ORDER:
            raise ValueError("max_spoiler_level is invalid")
        if self.version != POLICY_VERSION:
            raise ValueError("policy version is not supported")


@dataclass(frozen=True)
class ValidatedDirection:
    direction_key: str
    score: float
    payload: dict[str, Any]


class ResonanceScorer:
    """Application-owned implementation of the frozen V1 formula."""

    _WEIGHTS = {
        "cross_source_repetition": 0.30,
        "independent_source_diversity": 0.20,
        "emotion_specificity": 0.20,
        "experiential_cinematic_fit": 0.15,
        "interaction_signal": 0.10,
        "source_reliability": 0.05,
    }

    @staticmethod
    def _bounded(value: object, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be bounded finite [0,1]")
        result = float(value)
        if not math.isfinite(result) or not 0.0 <= result <= 1.0:
            raise ValueError(f"{label} must be bounded finite [0,1]")
        return result

    def score(
        self, signals: DirectionSignals, penalties: DirectionPenalties
    ) -> float:
        values: dict[str, float | None] = {
            field: getattr(signals, field) for field in self._WEIGHTS
        }
        for field, value in values.items():
            if field == "interaction_signal" and value is None:
                continue
            values[field] = self._bounded(value, field)
        if penalties.version != PENALTY_VERSION:
            raise ValueError("penalty version is not supported")
        spoiler = self._bounded(penalties.spoiler, "spoiler penalty")
        copyright_penalty = self._bounded(
            penalties.copyright, "copyright penalty"
        )
        conflict = self._bounded(penalties.conflict, "conflict penalty")
        included_weight = sum(
            weight
            for field, weight in self._WEIGHTS.items()
            if values[field] is not None
        )
        weighted = sum(
            weight * float(values[field])
            for field, weight in self._WEIGHTS.items()
            if values[field] is not None
        )
        raw = weighted / included_weight - spoiler - copyright_penalty - conflict
        return min(1.0, max(0.0, raw))


class _GroundedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=800)
    evidence_ids: list[UUID] = Field(min_length=0, max_length=64)
    kind: Literal["paraphrase", "verified_quote"] = "paraphrase"


class _ClusterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_key: str = Field(min_length=1, max_length=160)
    evidence_ids: list[UUID] = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=160)
    factual_statements: list[_GroundedModel] = Field(max_length=16)
    first_person_entry: _GroundedModel
    perceived_detail: _GroundedModel
    fit_for: list[_GroundedModel] = Field(max_length=8)
    not_fit_for: list[_GroundedModel] = Field(max_length=8)
    spoiler_level: Literal["none", "light", "moderate", "critical"]


class _ClusterOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clusters: list[_ClusterModel] = Field(max_length=16)


CLUSTER_SCHEMA_DIGEST = canonical_json_digest(_ClusterOutput.model_json_schema())


def _grounded(model: _GroundedModel) -> GroundedText:
    return GroundedText(
        text=model.text,
        evidence_ids=tuple(model.evidence_ids),
        kind=model.kind,
    )


def parse_cluster_proposals(raw: object) -> tuple[ClusterProposal, ...]:
    if not isinstance(raw, Mapping):
        raise ResonanceValidationError("cluster structured output is invalid")
    try:
        output = _ClusterOutput.model_validate(dict(raw))
    except ValidationError as error:
        raise ResonanceValidationError(
            "cluster structured output is invalid"
        ) from error
    return tuple(
        ClusterProposal(
            cluster_key=item.cluster_key,
            evidence_ids=tuple(item.evidence_ids),
            title=item.title,
            factual_statements=tuple(
                _grounded(value) for value in item.factual_statements
            ),
            first_person_entry=_grounded(item.first_person_entry),
            perceived_detail=_grounded(item.perceived_detail),
            fit_for=tuple(_grounded(value) for value in item.fit_for),
            not_fit_for=tuple(_grounded(value) for value in item.not_fit_for),
            spoiler_level=item.spoiler_level,
        )
        for item in output.clusters
    )


def stable_gap_codes(codes: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            set(codes),
            key=lambda code: (_GAP_RANK.get(code, len(_GAP_RANK)), code),
        )
    )


def _all_grounded(proposal: ClusterProposal) -> tuple[GroundedText, ...]:
    return (
        *proposal.factual_statements,
        proposal.first_person_entry,
        proposal.perceived_detail,
        *proposal.fit_for,
        *proposal.not_fit_for,
    )


def _claim_excerpt(
    claim: EvidenceClaim, source: SourceDocumentRevision
) -> str:
    start = claim.source_span.get("start")
    end = claim.source_span.get("end")
    if type(start) is not int or type(end) is not int:
        return ""
    return source.content[start:end]


def _has_grounding_overlap(detail: str, basis: Sequence[str]) -> bool:
    compact = "".join(detail.split())
    if len(compact) < 2:
        return any(compact and compact in value for value in basis)
    grams = {compact[index : index + 2] for index in range(len(compact) - 1)}
    return any(any(gram in value for gram in grams) for value in basis)


def _score_signal_payload(
    value: float | None,
    evidence_ids: Sequence[UUID],
    *,
    observed: bool | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "value": value,
        "evidence_ids": [str(item) for item in sorted(set(evidence_ids), key=str)],
    }
    if observed is not None:
        result["observed"] = observed
    return result


def _derive_signals(
    claims: Sequence[EvidenceClaim],
    sources_by_id: Mapping[UUID, SourceDocumentRevision],
) -> tuple[DirectionSignals, dict[str, dict[str, object]]]:
    evidence_ids = tuple(item.id for item in claims)
    sources = tuple(
        {
            item.source_document_revision_id: sources_by_id[
                item.source_document_revision_id
            ]
            for item in claims
        }.values()
    )
    domains = {item.registered_domain for item in sources}
    source_types = {item.source_type for item in sources}
    emotional = tuple(item for item in claims if item.claim_type == "emotional_reaction")
    experiential = tuple(
        item
        for item in claims
        if item.claim_type in {"plot_node", "emotional_reaction"}
    )
    observed_sources = tuple(
        item for item in sources if item.interaction_observed
    )
    repetition = min(1.0, len(domains) / 3.0)
    diversity = (
        min(1.0, len(domains) / 3.0)
        + min(1.0, len(source_types) / 2.0)
    ) / 2.0
    emotion = (
        sum(item.confidence for item in emotional) / len(emotional)
        if emotional
        else 0.0
    )
    cinematic = (
        sum(item.confidence for item in experiential) / len(experiential)
        if experiential
        else 0.0
    )
    interaction = (
        sum(float(item.interaction_signal) for item in observed_sources)
        / len(observed_sources)
        if observed_sources
        else None
    )
    reliability = (
        sum(
            _SOURCE_RELIABILITY.get(
                item.source_type, _SOURCE_RELIABILITY["unknown"]
            )
            for item in sources
        )
        / len(sources)
        if sources
        else 0.0
    )
    observed_source_ids = {item.id for item in observed_sources}
    interaction_evidence = tuple(
        item.id
        for item in claims
        if item.source_document_revision_id in observed_source_ids
    )
    signals = DirectionSignals(
        cross_source_repetition=repetition,
        independent_source_diversity=diversity,
        emotion_specificity=emotion,
        experiential_cinematic_fit=cinematic,
        interaction_signal=interaction,
        source_reliability=reliability,
    )
    payload = {
        "cross_source_repetition": _score_signal_payload(
            repetition, evidence_ids
        ),
        "independent_source_diversity": _score_signal_payload(
            diversity, evidence_ids
        ),
        "emotion_specificity": _score_signal_payload(
            emotion, tuple(item.id for item in emotional)
        ),
        "experiential_cinematic_fit": _score_signal_payload(
            cinematic, tuple(item.id for item in experiential)
        ),
        "interaction_signal": _score_signal_payload(
            interaction,
            interaction_evidence,
            observed=bool(observed_sources),
        ),
        "source_reliability": _score_signal_payload(
            reliability, evidence_ids
        ),
    }
    return signals, payload


def _derive_penalties(
    proposal: ClusterProposal,
    claims: Sequence[EvidenceClaim],
    pack: EvidencePackRevision,
) -> tuple[DirectionPenalties, dict[str, object]]:
    spoiler_level = max(
        (item.spoiler_level for item in claims),
        key=lambda value: _SPOILER_ORDER[value],
    )
    spoiler_ids = tuple(
        item.id
        for item in claims
        if _SPOILER_ORDER[item.spoiler_level]
        == max(_SPOILER_ORDER[value.spoiler_level] for value in claims)
    ) if claims else ()
    quote_ids = tuple(
        evidence_id
        for value in _all_grounded(proposal)
        if value.kind == "verified_quote"
        for evidence_id in value.evidence_ids
    )
    cluster_ids = {item.id for item in claims}
    conflict_penalty = 0.0
    conflict_ids: set[UUID] = set()
    for conflict in pack.conflicts:
        members = {
            UUID(str(item)) for item in conflict.get("evidence_ids", ())
        }
        touched = members & cluster_ids
        if not touched or conflict.get("unresolved"):
            continue
        conflict_ids.update(touched)
        conflict_penalty += {
            "minor": 0.02,
            "major": 0.05,
            "critical": 0.10,
        }.get(str(conflict.get("severity")), 0.0)
    penalties = DirectionPenalties(
        spoiler=_SPOILER_PENALTY[spoiler_level],
        copyright=min(0.10, 0.02 * len(set(quote_ids))),
        conflict=min(1.0, conflict_penalty),
    )
    payload = {
        "version": penalties.version,
        "spoiler": {
            "value": penalties.spoiler,
            "evidence_ids": [str(item) for item in sorted(set(spoiler_ids), key=str)],
        },
        "copyright": {
            "value": penalties.copyright,
            "evidence_ids": [str(item) for item in sorted(set(quote_ids), key=str)],
        },
        "conflict": {
            "value": penalties.conflict,
            "evidence_ids": [str(item) for item in sorted(conflict_ids, key=str)],
        },
    }
    return penalties, payload


def _stable_direction_key(evidence_ids: Sequence[UUID]) -> str:
    material = "\x1f".join(str(item) for item in sorted(evidence_ids, key=str))
    return "resonance:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _grounded_payload(item: GroundedText) -> dict[str, object]:
    return item.model_dump(mode="json")


def validate_cluster(
    proposal: ClusterProposal,
    *,
    pack: EvidencePackRevision,
    claims_by_id: Mapping[UUID, EvidenceClaim],
    sources_by_id: Mapping[UUID, SourceDocumentRevision],
    policy: ResonancePolicy,
    model_version: str,
    prompt_version: str,
    scorer: ResonanceScorer | None = None,
) -> tuple[ValidatedDirection | None, tuple[str, ...]]:
    gaps: list[str] = []
    # All score inputs and the persisted payload must use the same canonical
    # order. Model proposals are allowed to return IDs in any order, while the
    # immutable payload stores them sorted; scoring an unsorted first pass can
    # otherwise produce a different floating-point digest during revalidation.
    evidence_ids = tuple(sorted(proposal.evidence_ids, key=str))
    if len(evidence_ids) != len(set(evidence_ids)):
        gaps.append("duplicate_evidence_id")
    selected_set = set(evidence_ids)
    pack_set = set(pack.evidence_ids)
    if not selected_set.issubset(pack_set) or not selected_set.issubset(claims_by_id):
        gaps.append("foreign_evidence_id")
    if gaps:
        return None, stable_gap_codes(gaps)

    claims = tuple(claims_by_id[item] for item in evidence_ids)
    if any(
        item.project_id != pack.project_id
        or item.research_job_id != pack.research_job_id
        or item.source_document_revision_id not in sources_by_id
        for item in claims
    ):
        gaps.append("evidence_lineage_mismatch")
    selected_sources = {
        item.source_document_revision_id: sources_by_id[item.source_document_revision_id]
        for item in claims
        if item.source_document_revision_id in sources_by_id
    }
    if any(
        source.project_id != pack.project_id
        or source.research_job_id != pack.research_job_id
        for source in selected_sources.values()
    ):
        gaps.append("evidence_lineage_mismatch")

    domains = {item.registered_domain for item in selected_sources.values()}
    source_types = {item.source_type for item in selected_sources.values()}
    # The model may choose only the strongest extracted claims from a pack, so
    # the selected cluster need not reference the generated source directly.
    # The immutable pack coverage is the authority for whether AI completion
    # actually occurred; content_mode alone is insufficient because a sparse
    # third-party-only pack also has no original text.
    ai_completed_pack = (
        pack.coverage.get("content_mode") == "ai_completed"
        and int(pack.coverage.get("ai_generated_source_count", 0)) > 0
        and pack.coverage.get("disclosure_required") is True
    )
    # An AI-completed direction is allowed to proceed with sparse web evidence,
    # but its low-reliability provenance remains explicit in the frozen pack and
    # public projection. It is never presented as an original-text quotation.
    if not ai_completed_pack:
        if len(domains) < 3:
            gaps.append("independent_sources_insufficient")
        if len(source_types) < 2:
            gaps.append("source_types_insufficient")
    claim_types = {item.claim_type for item in claims}
    for claim_type, gap in (
        ("plot_node", "plot_node_missing"),
        ("emotional_reaction", "emotional_reaction_missing"),
        ("reader_fit", "reader_fit_missing"),
    ):
        if claim_type not in claim_types:
            gaps.append(gap)

    max_spoiler = max(
        (item.spoiler_level for item in claims),
        key=lambda value: _SPOILER_ORDER[value],
    )
    if proposal.spoiler_level != max_spoiler:
        gaps.append("spoiler_metadata_mismatch")
    gate_spoiler = max(
        (max_spoiler, proposal.spoiler_level),
        key=lambda value: _SPOILER_ORDER[value],
    )
    if _SPOILER_ORDER[gate_spoiler] > _SPOILER_ORDER[policy.max_spoiler_level]:
        gaps.append("spoiler_policy_exceeded")

    if not proposal.fit_for:
        gaps.append("fit_for_missing")
    if not proposal.not_fit_for:
        gaps.append("not_fit_for_missing")

    all_grounded = _all_grounded(proposal)
    for value in all_grounded:
        refs = tuple(value.evidence_ids)
        if not refs:
            gaps.append("ungrounded_statement")
        if len(refs) != len(set(refs)):
            gaps.append("duplicate_evidence_id")
        if not set(refs).issubset(selected_set):
            gaps.append("foreign_evidence_id")
        grounded_basis = tuple(
            text
            for evidence_id in refs
            if evidence_id in claims_by_id
            and claims_by_id[evidence_id].source_document_revision_id
            in sources_by_id
            for text in (
                claims_by_id[evidence_id].normalized_claim,
                sources_by_id[
                    claims_by_id[evidence_id].source_document_revision_id
                ].content,
            )
        )
        if refs and not _has_grounding_overlap(value.text, grounded_basis):
            gaps.append("ungrounded_statement")

    entry = proposal.first_person_entry.text
    perceived = proposal.perceived_detail.text
    entry_refs = set(proposal.first_person_entry.evidence_ids)
    plot_ids = {item.id for item in claims if item.claim_type == "plot_node"}
    perception_basis = tuple(
        text
        for evidence_id in proposal.perceived_detail.evidence_ids
        if evidence_id in claims_by_id
        for text in (
            claims_by_id[evidence_id].normalized_claim,
            sources_by_id[
                claims_by_id[evidence_id].source_document_revision_id
            ].content,
        )
    )
    if (
        "我" not in entry
        or not perceived
        or perceived not in entry
        or any(token in entry for token in _POV_FORBIDDEN)
        or not entry_refs
        or not (entry_refs & plot_ids)
        or not proposal.perceived_detail.evidence_ids
        or not _has_grounding_overlap(perceived, perception_basis)
    ):
        gaps.append("pov_entry_not_grounded")

    for value in all_grounded:
        if value.kind == "paraphrase" and (
            any(mark in value.text for mark in ("“", "”", "‘", "’"))
            or (
                len(value.text) >= 2
                and value.text[0] in {"\"", "'"}
                and value.text[-1] == value.text[0]
            )
        ):
            gaps.append("unverified_direct_quote")
        if value.kind != "verified_quote":
            continue
        quoted = value.text.strip("‘’“”\"'")
        verified = False
        for evidence_id in value.evidence_ids:
            claim = claims_by_id.get(evidence_id)
            if claim is None or not claim.is_direct_quote:
                continue
            source = sources_by_id.get(claim.source_document_revision_id)
            if source is not None and quoted == _claim_excerpt(claim, source):
                verified = True
                break
        if not verified:
            gaps.append("unverified_direct_quote")

    for value in all_grounded:
        if value.kind != "paraphrase" or len(value.text) < 20:
            continue
        if any(
            value.text in sources_by_id[claim.source_document_revision_id].content
            for claim in claims
            if claim.id in value.evidence_ids
        ):
            gaps.append("copyright_risk")

    for conflict in pack.conflicts:
        if (
            conflict.get("severity") == "critical"
            and bool(conflict.get("unresolved"))
            and selected_set
            & {UUID(str(item)) for item in conflict.get("evidence_ids", ())}
        ):
            gaps.append("critical_conflict_unresolved")

    gaps_tuple = stable_gap_codes(gaps)
    if gaps_tuple:
        return None, gaps_tuple

    signals, signal_payload = _derive_signals(claims, sources_by_id)
    penalties, penalty_payload = _derive_penalties(proposal, claims, pack)
    score_value = (scorer or ResonanceScorer()).score(signals, penalties)
    direction_key = _stable_direction_key(evidence_ids)
    payload: dict[str, Any] = {
        "schema_version": DIRECTION_SCHEMA_VERSION,
        "validator_version": RESONANCE_VALIDATOR_VERSION,
        "clustering_version": CLUSTERING_VERSION,
        "model_version": model_version,
        "prompt_version": prompt_version,
        "cluster_schema_version": CLUSTER_SCHEMA_VERSION,
        "cluster_schema_digest": CLUSTER_SCHEMA_DIGEST,
        "policy_version": policy.version,
        "policy_max_spoiler_level": policy.max_spoiler_level,
        "evidence_ids": [str(item) for item in sorted(evidence_ids, key=str)],
        "title": proposal.title,
        "factual_statements": [
            _grounded_payload(item) for item in proposal.factual_statements
        ],
        "first_person_entry": _grounded_payload(proposal.first_person_entry),
        "perceived_detail": _grounded_payload(proposal.perceived_detail),
        "fit_for": [_grounded_payload(item) for item in proposal.fit_for],
        "not_fit_for": [
            _grounded_payload(item) for item in proposal.not_fit_for
        ],
        "spoiler_level": proposal.spoiler_level,
        "signals": signal_payload,
        "penalties": penalty_payload,
        "score": score_value,
        "score_version": DIRECTION_SCORE_VERSION,
    }
    return ValidatedDirection(direction_key, score_value, payload), ()


_PAYLOAD_KEYS = {
    "schema_version",
    "validator_version",
    "clustering_version",
    "model_version",
    "prompt_version",
    "cluster_schema_version",
    "cluster_schema_digest",
    "policy_version",
    "policy_max_spoiler_level",
    "evidence_ids",
    "title",
    "factual_statements",
    "first_person_entry",
    "perceived_detail",
    "fit_for",
    "not_fit_for",
    "spoiler_level",
    "signals",
    "penalties",
    "score",
    "score_version",
}


def _proposal_from_payload(payload: Mapping[str, Any]) -> ClusterProposal:
    raw = {
        "clusters": [
            {
                "cluster_key": "persisted",
                "evidence_ids": payload.get("evidence_ids"),
                "title": payload.get("title"),
                "factual_statements": payload.get("factual_statements"),
                "first_person_entry": payload.get("first_person_entry"),
                "perceived_detail": payload.get("perceived_detail"),
                "fit_for": payload.get("fit_for"),
                "not_fit_for": payload.get("not_fit_for"),
                "spoiler_level": payload.get("spoiler_level"),
            }
        ]
    }
    return parse_cluster_proposals(raw)[0]


def validate_persisted_direction_payload(
    direction_key: str,
    payload: Mapping[str, Any],
    *,
    pack: EvidencePackRevision,
    claims_by_id: Mapping[UUID, EvidenceClaim],
    sources_by_id: Mapping[UUID, SourceDocumentRevision],
) -> dict[str, Any]:
    if set(payload) != _PAYLOAD_KEYS:
        raise ValueError("direction payload schema is invalid")
    for key, expected in (
        ("schema_version", DIRECTION_SCHEMA_VERSION),
        ("validator_version", RESONANCE_VALIDATOR_VERSION),
        ("clustering_version", CLUSTERING_VERSION),
        ("cluster_schema_version", CLUSTER_SCHEMA_VERSION),
        ("cluster_schema_digest", CLUSTER_SCHEMA_DIGEST),
        ("policy_version", POLICY_VERSION),
        ("score_version", DIRECTION_SCORE_VERSION),
    ):
        if payload.get(key) != expected:
            raise ValueError(f"direction {key} is invalid")
    if not isinstance(payload.get("model_version"), str) or not payload["model_version"]:
        raise ValueError("direction model_version is invalid")
    if not isinstance(payload.get("prompt_version"), str) or not payload["prompt_version"]:
        raise ValueError("direction prompt_version is invalid")
    try:
        proposal = _proposal_from_payload(payload)
        policy = ResonancePolicy(
            max_spoiler_level=str(payload["policy_max_spoiler_level"]),  # type: ignore[arg-type]
            version=str(payload["policy_version"]),
        )
    except (ResonanceValidationError, TypeError, ValueError) as error:
        raise ValueError("direction evidence payload is invalid") from error
    validated, gaps = validate_cluster(
        proposal,
        pack=pack,
        claims_by_id=claims_by_id,
        sources_by_id=sources_by_id,
        policy=policy,
        model_version=str(payload["model_version"]),
        prompt_version=str(payload["prompt_version"]),
    )
    if validated is None:
        raise ValueError(
            "direction evidence payload is invalid: " + ",".join(gaps)
        )
    if validated.direction_key != direction_key:
        raise ValueError("direction evidence key is invalid")
    expected_score = validated.payload["score"]
    actual_score = payload.get("score")
    if (
        isinstance(actual_score, bool)
        or not isinstance(actual_score, (int, float))
        or not math.isfinite(float(actual_score))
        or not math.isclose(
            float(actual_score), float(expected_score), rel_tol=0.0, abs_tol=1e-12
        )
    ):
        raise ValueError("direction score payload is invalid")
    if canonical_json_digest(dict(payload)) != canonical_json_digest(
        validated.payload
    ):
        raise ValueError("direction score or evidence payload is invalid")
    return validated.payload


__all__ = [
    "CLUSTER_SCHEMA_DIGEST",
    "CLUSTER_SCHEMA_VERSION",
    "CLUSTERING_VERSION",
    "DIRECTION_SCHEMA_VERSION",
    "DIRECTION_SCORE_VERSION",
    "DirectionPenalties",
    "DirectionSignals",
    "GAP_CODE_ORDER",
    "GroundedText",
    "PENALTY_VERSION",
    "POLICY_VERSION",
    "RESONANCE_VALIDATOR_VERSION",
    "ClusterProposal",
    "ResonancePolicy",
    "ResonanceScorer",
    "ResonanceValidationError",
    "ValidatedDirection",
    "parse_cluster_proposals",
    "stable_gap_codes",
    "validate_cluster",
    "validate_persisted_direction_payload",
]
