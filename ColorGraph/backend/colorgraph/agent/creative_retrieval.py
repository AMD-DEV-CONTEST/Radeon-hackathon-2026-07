from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from colorgraph.agent.creative_contracts import (
    BriefRetrieval,
    CreativeBrief,
    CreativePossibilityCard,
    FailureCard,
    Identifier,
    NonEmptyString,
    NormalizedScore,
    OperationCard,
    ProjectContextPack,
    ProjectVisualThesis,
    ProtectedAttribute,
    RetrievalBundle,
    RetrievalExpansion,
    RetrievalRoute,
    RetrievedPossibility,
    Sha256,
    StrictFrozenModel,
    canonical_sha256,
)

CREATIVE_RETRIEVAL_VERSION = "colorgraph.creative-possibility-retrieval/v1"
TEXT_EMBEDDING_VERSION = "colorgraph.local-text-features/v1"

_WORD_PATTERN = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]", re.IGNORECASE)


class RetrievalFilterContext(StrictFrozenModel):
    media_type: Identifier
    color_domain: Identifier
    scope: Identifier
    available_capabilities: list[Identifier]
    allowed_rights: list[NonEmptyString]
    required_protections: list[ProtectedAttribute]
    permitted_use: Identifier = "creative_retrieval"

class HardFilterRecord(StrictFrozenModel):
    card_id: Identifier
    allowed: bool
    reasons: list[NonEmptyString]


class RetrievalRouteAudit(StrictFrozenModel):
    brief_id: Identifier
    route: RetrievalRoute
    query: NonEmptyString
    hard_filters: list[HardFilterRecord]
    candidate_count: int = Field(ge=0)
    selected_card_ids: list[Identifier]
    low_relevance_card_ids: list[Identifier]
    diversity_excluded_card_ids: list[Identifier]


class CreativeRetrievalMetrics(StrictFrozenModel):
    route_coverage: NormalizedScore
    source_diversity: NormalizedScore
    counterexample_hit_rate: NormalizedScore
    low_relevance_rejection_rate: NormalizedScore
    convergence_risk_rate: NormalizedScore
    selected_card_count: int = Field(ge=0)
    hard_filter_rejection_count: int = Field(ge=0)
    low_relevance_candidate_count: int = Field(ge=0)


class CreativeRetrievalAudit(StrictFrozenModel):
    schema_version: Literal["colorgraph.creative-retrieval-audit/v1"] = (
        "colorgraph.creative-retrieval-audit/v1"
    )
    retrieval_version: str = CREATIVE_RETRIEVAL_VERSION
    index_version: Identifier
    thesis_digest_before: Sha256
    thesis_digest_after: Sha256
    brief_digests_before: dict[Identifier, Sha256]
    route_audits: list[RetrievalRouteAudit]
    metrics: CreativeRetrievalMetrics


class SourceDeletionReport(StrictFrozenModel):
    source_id: Identifier
    removed_possibility_card_ids: list[Identifier]
    removed_operation_card_ids: list[Identifier]
    removed_failure_card_ids: list[Identifier]
    invalidated_embedding_ids: list[Sha256]


@dataclass(frozen=True, slots=True)
class CreativeRetrievalResult:
    bundle: RetrievalBundle
    audit: CreativeRetrievalAudit


def _tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    words = _WORD_PATTERN.findall(normalized)
    compact = re.sub(r"\s+", " ", normalized).strip()
    character_ngrams = [
        f"char:{compact[index:index + 3]}"
        for index in range(max(0, len(compact) - 2))
        if " " not in compact[index : index + 3]
    ]
    return [*words, *character_ngrams]


def _embed(text: str) -> dict[str, float]:
    counts: dict[str, float] = {}
    for token in _tokens(text):
        counts[token] = counts.get(token, 0) + 1
    norm = math.sqrt(sum(value * value for value in counts.values()))
    if norm == 0:
        return {}
    return {token: value / norm for token, value in counts.items()}


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return max(
        0.0,
        min(1.0, sum(value * right.get(token, 0) for token, value in left.items())),
    )


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _card_text(
    card: CreativePossibilityCard,
    route: RetrievalRoute | None = None,
) -> str:
    common = [
        card.concept,
        *card.scene_terms,
        *card.emotion_terms,
        *card.possible_visual_cues,
    ]
    if route == RetrievalRoute.SAME_SCENE_DIFFERENT_EMOTION:
        routed = [*card.alternatives, *card.possible_visual_cues]
    elif route == RetrievalRoute.SAME_EMOTION_DIFFERENT_SCENE:
        routed = [*card.possible_grade_strategies, *card.emotion_terms]
    elif route == RetrievalRoute.COUNTEREXAMPLE_OR_FAILURE:
        routed = [*card.counterexamples, *card.cliche_risks]
    else:
        routed = [
            *card.possible_grade_strategies,
            *card.alternatives,
            *card.cliche_risks,
            *card.counterexamples,
        ]
    return " ".join([*common, *routed])


def _query_for_route(
    brief: CreativeBrief,
    *,
    scene_observations: str,
    route: RetrievalRoute,
) -> str:
    hierarchy = " ".join(
        f"{item.target} {item.rationale}" for item in brief.visual_hierarchy
    )
    if route == RetrievalRoute.SAME_SCENE_DIFFERENT_EMOTION:
        return " ".join(
            [
                scene_observations,
                hierarchy,
                brief.interpretation,
                "alternative emotional reading",
            ]
        )
    if route == RetrievalRoute.SAME_EMOTION_DIFFERENT_SCENE:
        return " ".join(
            [
                brief.emotional_target,
                brief.interpretation,
                *(
                    item.rationale
                    for item in brief.possible_color_language
                ),
                "different scene same emotional relationship",
            ]
        )
    return " ".join(
        [
            brief.interpretation,
            *brief.cliche_risks,
            *brief.failure_conditions,
            "counterexample failure avoid assumption",
        ]
    )


def _hard_filter_reasons(
    card: CreativePossibilityCard,
    filters: RetrievalFilterContext,
) -> list[str]:
    reasons: list[str] = []
    if filters.media_type not in card.media_types:
        reasons.append("media_type")
    if filters.color_domain not in card.color_domains:
        reasons.append("color_domain")
    if filters.scope not in card.scopes:
        reasons.append("scope")
    if not set(card.required_capabilities) <= set(filters.available_capabilities):
        reasons.append("capability")
    if card.provenance.rights not in filters.allowed_rights:
        reasons.append("rights")
    if filters.permitted_use not in card.provenance.permitted_uses:
        reasons.append("permitted_use")
    if not set(filters.required_protections) <= set(card.compatible_protections):
        reasons.append("protected_attribute")
    return reasons


class CreativeKnowledgeIndex:
    """Versioned card registry with strict consumer boundaries."""

    def __init__(self, index_version: str) -> None:
        if not index_version:
            raise ValueError("knowledge index version must not be empty")
        self.index_version = index_version
        self._possibilities: dict[str, CreativePossibilityCard] = {}
        self._operations: dict[str, OperationCard] = {}
        self._failures: dict[str, FailureCard] = {}
        self._vectors: dict[str, dict[str, float]] = {}
        self._embedding_ids: dict[str, str] = {}

    @staticmethod
    def _publish_immutable[CardT](
        collection: dict[str, CardT],
        card_id: str,
        card: CardT,
    ) -> None:
        existing = collection.get(card_id)
        if existing is not None and existing != card:
            raise ValueError(f"refusing to replace immutable knowledge card {card_id}")
        collection[card_id] = card

    def _assert_unique_boundary(self, card_id: str, boundary: str) -> None:
        occupied = {
            "possibility": card_id in self._possibilities,
            "operation": card_id in self._operations,
            "failure": card_id in self._failures,
        }
        conflicting = [name for name, present in occupied.items() if present and name != boundary]
        if conflicting:
            raise ValueError(
                f"card ID {card_id} already belongs to the {conflicting[0]} boundary"
            )

    def publish_possibility(self, card: CreativePossibilityCard) -> None:
        if not card.provenance.redistributable:
            raise ValueError("publishable creative knowledge must be redistributable")
        self._assert_unique_boundary(card.card_id, "possibility")
        self._publish_immutable(self._possibilities, card.card_id, card)
        self._vectors[card.card_id] = _embed(_card_text(card))
        self._embedding_ids[card.card_id] = canonical_sha256(
            {
                "embedding_version": TEXT_EMBEDDING_VERSION,
                "card": card.model_dump(mode="json"),
            }
        )

    def publish_operation(self, card: OperationCard) -> None:
        self._assert_unique_boundary(card.card_id, "operation")
        self._publish_immutable(self._operations, card.card_id, card)

    def publish_failure(self, card: FailureCard) -> None:
        self._assert_unique_boundary(card.card_id, "failure")
        self._publish_immutable(self._failures, card.card_id, card)

    def possibility_cards_for_retrieval(self) -> tuple[CreativePossibilityCard, ...]:
        return tuple(self._possibilities[key] for key in sorted(self._possibilities))

    def operation_cards_for_compiler(self) -> tuple[OperationCard, ...]:
        return tuple(self._operations[key] for key in sorted(self._operations))

    def failure_cards_for_qc(self) -> tuple[FailureCard, ...]:
        return tuple(self._failures[key] for key in sorted(self._failures))

    def embedding_id(self, card_id: str) -> str | None:
        return self._embedding_ids.get(card_id)

    def embedding_count(self) -> int:
        return len(self._vectors)

    def vector(self, card_id: str) -> dict[str, float]:
        return self._vectors[card_id]

    def delete_source(self, source_id: str) -> SourceDeletionReport:
        if not source_id:
            raise ValueError("source ID must not be empty")

        def matching[CardT](collection: dict[str, CardT]) -> list[str]:
            return sorted(
                card_id
                for card_id, card in collection.items()
                if card.provenance.source_id == source_id
            )

        possibilities = matching(self._possibilities)
        operations = matching(self._operations)
        failures = matching(self._failures)
        invalidated = [
            self._embedding_ids[card_id]
            for card_id in possibilities
            if card_id in self._embedding_ids
        ]
        for card_id in possibilities:
            self._possibilities.pop(card_id, None)
            self._vectors.pop(card_id, None)
            self._embedding_ids.pop(card_id, None)
        for card_id in operations:
            self._operations.pop(card_id, None)
        for card_id in failures:
            self._failures.pop(card_id, None)
        return SourceDeletionReport(
            source_id=source_id,
            removed_possibility_card_ids=possibilities,
            removed_operation_card_ids=operations,
            removed_failure_card_ids=failures,
            invalidated_embedding_ids=invalidated,
        )


def _select_diverse(
    candidates: list[tuple[CreativePossibilityCard, float]],
    *,
    index: CreativeKnowledgeIndex,
    maximum: int,
) -> list[tuple[CreativePossibilityCard, float, float]]:
    remaining = sorted(candidates, key=lambda item: (-item[1], item[0].card_id))
    selected: list[tuple[CreativePossibilityCard, float, float]] = []
    while remaining and len(selected) < maximum:
        ranked: list[tuple[float, float, str, CreativePossibilityCard]] = []
        selected_cards = [item[0] for item in selected]
        selected_sources = {item.provenance.source_id for item in selected_cards}
        selected_templates = {item.template_family for item in selected_cards}
        for card, relevance in remaining:
            similarity = max(
                (
                    _cosine(index.vector(card.card_id), index.vector(item.card_id))
                    for item in selected_cards
                ),
                default=0,
            )
            source_bonus = (
                0.12 if selected_cards and card.provenance.source_id not in selected_sources else 0
            )
            template_penalty = (
                0.12 if card.template_family in selected_templates else 0
            )
            mmr_score = (
                0.76 * relevance
                - 0.18 * similarity
                + source_bonus
                - template_penalty
            )
            ranked.append((mmr_score, relevance, card.card_id, card))
        mmr_score, relevance, _, chosen = max(
            ranked,
            key=lambda item: (item[0], item[1], item[2]),
        )
        selected.append((chosen, relevance, mmr_score))
        remaining = [item for item in remaining if item[0].card_id != chosen.card_id]
    return selected


def retrieve_creative_possibilities(
    *,
    thesis: ProjectVisualThesis,
    thesis_asset_id: str,
    thesis_sha256: str,
    context: ProjectContextPack,
    index: CreativeKnowledgeIndex,
    filters: RetrievalFilterContext,
    relevance_threshold: float = 0.24,
    maximum_per_route: int = 2,
) -> CreativeRetrievalResult:
    if not 0 <= relevance_threshold <= 1:
        raise ValueError("relevance threshold must be normalized")
    if maximum_per_route <= 0:
        raise ValueError("maximum cards per route must be positive")
    if set(brief.scene_id for brief in thesis.briefs) - set(context.allowed_scene_ids):
        raise ValueError("thesis contains a scene outside the evidence context")

    thesis_before = canonical_sha256(thesis)
    brief_digests = {
        brief.brief_id: canonical_sha256(brief)
        for brief in thesis.briefs
    }
    cards = list(index.possibility_cards_for_retrieval())
    selected_by_id: dict[str, CreativePossibilityCard] = {}
    selected_by_brief: dict[str, list[str]] = {}
    retrievals: list[BriefRetrieval] = []
    route_audits: list[RetrievalRouteAudit] = []
    selected_counterexample_routes = 0
    counterexample_routes = 0
    total_routes = len(thesis.briefs) * len(RetrievalRoute)
    covered_routes = 0
    hard_rejections = 0
    low_relevance_total = 0

    for brief in thesis.briefs:
        scene_observations = " ".join(
            item.summary
            for item in context.evidence
            if item.scene_id in {None, brief.scene_id}
        )
        for route in RetrievalRoute:
            if route == RetrievalRoute.COUNTEREXAMPLE_OR_FAILURE:
                counterexample_routes += 1
            query = _query_for_route(
                brief,
                scene_observations=scene_observations,
                route=route,
            )
            query_vector = _embed(query)
            hard_records: list[HardFilterRecord] = []
            hard_rejected: dict[str, list[str]] = {}
            scored: list[tuple[CreativePossibilityCard, float]] = []
            low_relevance: list[str] = []
            for card in cards:
                reasons = _hard_filter_reasons(card, filters)
                hard_records.append(
                    HardFilterRecord(
                        card_id=card.card_id,
                        allowed=not reasons,
                        reasons=reasons,
                    )
                )
                if reasons:
                    hard_rejected[card.card_id] = reasons
                    hard_rejections += 1
                    continue
                semantic_score = _cosine(
                    query_vector,
                    _embed(_card_text(card, route)),
                )
                route_bonus = 0.15 if route in card.route_support else 0
                score = min(1.0, 0.85 * semantic_score + route_bonus)
                if score < relevance_threshold:
                    low_relevance.append(card.card_id)
                    low_relevance_total += 1
                    continue
                scored.append((card, score))
            selected = _select_diverse(
                scored,
                index=index,
                maximum=maximum_per_route,
            )
            selected_ids = {item[0].card_id for item in selected}
            if selected_ids:
                covered_routes += 1
                if route == RetrievalRoute.COUNTEREXAMPLE_OR_FAILURE and any(
                    route in card.route_support for card, _, _ in selected
                ):
                    selected_counterexample_routes += 1
            diversity_excluded = sorted(
                card.card_id for card, _ in scored if card.card_id not in selected_ids
            )
            results: list[RetrievedPossibility] = []
            score_by_id = {card.card_id: score for card, score in scored}
            selected_mmr = {
                card.card_id: mmr for card, _, mmr in selected
            }
            for card in cards:
                if card.card_id in selected_ids:
                    score = score_by_id[card.card_id]
                    results.append(
                        RetrievedPossibility(
                            card_id=card.card_id,
                            card_version=card.card_version,
                            route=route,
                            score=round(score, 6),
                            source_uri=card.provenance.source_uri,
                            rights=card.provenance.rights,
                            selected_reason=(
                                f"route={route.value}; relevance={score:.4f}; "
                                f"diversity={selected_mmr[card.card_id]:.4f}"
                            ),
                        )
                    )
                    selected_by_id[card.card_id] = card
                    selected_by_brief.setdefault(brief.brief_id, []).append(
                        card.card_id
                    )
                elif card.card_id in hard_rejected:
                    results.append(
                        RetrievedPossibility(
                            card_id=card.card_id,
                            card_version=card.card_version,
                            route=route,
                            score=0,
                            source_uri=card.provenance.source_uri,
                            rights=card.provenance.rights,
                            excluded_reason=(
                                "hard_filter:" + ",".join(hard_rejected[card.card_id])
                            ),
                        )
                    )
                elif card.card_id in low_relevance:
                    route_score = min(
                        1.0,
                        0.85
                        * _cosine(
                            query_vector,
                            _embed(_card_text(card, route)),
                        )
                        + (0.15 if route in card.route_support else 0),
                    )
                    results.append(
                        RetrievedPossibility(
                            card_id=card.card_id,
                            card_version=card.card_version,
                            route=route,
                            score=round(route_score, 6),
                            source_uri=card.provenance.source_uri,
                            rights=card.provenance.rights,
                            excluded_reason=(
                                f"ood_below_threshold:{relevance_threshold:.4f}"
                            ),
                        )
                    )
                else:
                    results.append(
                        RetrievedPossibility(
                            card_id=card.card_id,
                            card_version=card.card_version,
                            route=route,
                            score=round(score_by_id[card.card_id], 6),
                            source_uri=card.provenance.source_uri,
                            rights=card.provenance.rights,
                            excluded_reason="diversity_constraint",
                        )
                    )
            retrievals.append(
                BriefRetrieval(
                    brief_id=brief.brief_id,
                    query=query,
                    route=route,
                    results=results,
                    low_relevance_rejected=bool(low_relevance),
                )
            )
            route_audits.append(
                RetrievalRouteAudit(
                    brief_id=brief.brief_id,
                    route=route,
                    query=query,
                    hard_filters=hard_records,
                    candidate_count=len(scored),
                    selected_card_ids=sorted(selected_ids),
                    low_relevance_card_ids=sorted(low_relevance),
                    diversity_excluded_card_ids=diversity_excluded,
                )
            )

    templates_by_brief = {
        brief_id: {
            selected_by_id[card_id].template_family
            for card_id in card_ids
        }
        for brief_id, card_ids in selected_by_brief.items()
    }
    risky_briefs = {
        brief_id
        for brief_id, card_ids in selected_by_brief.items()
        if len(card_ids) > 1 and len(templates_by_brief[brief_id]) == 1
    }
    briefs_by_scene: dict[str, list[CreativeBrief]] = {}
    for brief in thesis.briefs:
        briefs_by_scene.setdefault(brief.scene_id, []).append(brief)
    for scene_briefs in briefs_by_scene.values():
        family_sets = [
            templates_by_brief.get(brief.brief_id, set())
            for brief in scene_briefs
            if templates_by_brief.get(brief.brief_id)
        ]
        if len(family_sets) >= 2 and len(set.union(*family_sets)) == 1:
            risky_briefs.update(brief.brief_id for brief in scene_briefs)

    expansions: list[RetrievalExpansion] = []
    for brief in thesis.briefs:
        card_ids = _deduplicate(selected_by_brief.get(brief.brief_id, []))
        brief_cards = [selected_by_id[card_id] for card_id in card_ids]
        expansions.append(
            RetrievalExpansion(
                brief_id=brief.brief_id,
                frozen_brief_sha256=brief_digests[brief.brief_id],
                selected_card_ids=card_ids,
                expanded_possibilities=_deduplicate(
                    [
                        value
                        for card in brief_cards
                        for value in [card.concept, *card.possible_grade_strategies]
                    ]
                ),
                challenges=_deduplicate(
                    [
                        value
                        for card in brief_cards
                        for value in [*card.cliche_risks, *card.counterexamples]
                    ]
                ),
                convergence_risk=brief.brief_id in risky_briefs,
            )
        )

    thesis_after = canonical_sha256(thesis)
    if thesis_after != thesis_before:
        raise RuntimeError("retrieval mutated the frozen project thesis")
    selected_cards = [
        selected_by_id[card_id]
        for card_id in sorted(selected_by_id)
    ]
    selected_sources = {
        card.provenance.source_id for card in selected_cards
    }
    selected_count = len(selected_cards)
    metrics = CreativeRetrievalMetrics(
        route_coverage=covered_routes / total_routes if total_routes else 0,
        source_diversity=(
            len(selected_sources) / selected_count if selected_count else 0
        ),
        counterexample_hit_rate=(
            selected_counterexample_routes / counterexample_routes
            if counterexample_routes
            else 0
        ),
        low_relevance_rejection_rate=1.0,
        convergence_risk_rate=(
            len(risky_briefs) / len(thesis.briefs) if thesis.briefs else 0
        ),
        selected_card_count=selected_count,
        hard_filter_rejection_count=hard_rejections,
        low_relevance_candidate_count=low_relevance_total,
    )
    bundle = RetrievalBundle(
        thesis_asset_id=thesis_asset_id,
        thesis_sha256=thesis_sha256,
        retrievals=retrievals,
        index_version=index.index_version,
        empty_bundle_reason=(
            None
            if selected_cards
            else "No possibility card passed hard filters and the OOD relevance threshold."
        ),
        selected_cards=selected_cards,
        expansions=expansions,
    )
    return CreativeRetrievalResult(
        bundle=bundle,
        audit=CreativeRetrievalAudit(
            index_version=index.index_version,
            thesis_digest_before=thesis_before,
            thesis_digest_after=thesis_after,
            brief_digests_before=brief_digests,
            route_audits=route_audits,
            metrics=metrics,
        ),
    )
