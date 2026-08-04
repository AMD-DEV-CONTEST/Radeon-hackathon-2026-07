from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Literal, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from policyseal.agent.checkpoints import TaskCheckpointStore
from policyseal.agent.llm_client import (
    CompletionClient,
    LocalInferenceError,
    category_evidence_for_file,
)
from policyseal.agent.schemas import (
    ClassificationBatch,
    ClassificationOutcome,
    ClassificationRun,
    CompletionAttempt,
    ModelClassification,
    SemanticRegionInput,
)
from policyseal.domain.enums import ContentCategory, FileKind
from policyseal.domain.models import DocumentRegion

logger = logging.getLogger(__name__)


class _ClassificationState(TypedDict, total=False):
    regions: tuple[SemanticRegionInput, ...]
    original_categories: dict[str, ContentCategory]
    deterministic: tuple[ClassificationOutcome, ...]
    uncertain: tuple[SemanticRegionInput, ...]
    attempts: tuple[CompletionAttempt, ...]
    validated: tuple[ClassificationOutcome, ...]
    failure_code: str
    outcomes: tuple[ClassificationOutcome, ...]


class SemanticClassificationGraph:
    def __init__(
        self,
        client: CompletionClient,
        *,
        min_confidence: float = 0.8,
        batch_size: int = 8,
        consistency_passes: int = 2,
        checkpoint_store: TaskCheckpointStore | None = None,
    ) -> None:
        if not 0 <= min_confidence <= 1:
            raise ValueError("minimum confidence must be between zero and one")
        if batch_size < 1 or consistency_passes < 1:
            raise ValueError("batch size and consistency passes must be positive")
        self.client = client
        self.min_confidence = min_confidence
        self.batch_size = batch_size
        self.consistency_passes = consistency_passes
        self.checkpoint_store = checkpoint_store
        self.last_run = ClassificationRun(())
        builder = StateGraph(_ClassificationState)
        builder.add_node("deterministic_preclassification", self._preclassify)
        builder.add_node("local_model_call", self._model_call)
        builder.add_node("typed_validation_and_evidence", self._validate)
        builder.add_node("human_interruption", self._human_review)
        builder.add_node("finish", self._finish)
        builder.add_edge(START, "deterministic_preclassification")
        builder.add_conditional_edges(
            "deterministic_preclassification",
            self._route_after_preclassification,
            {"local_model_call": "local_model_call", "finish": "finish"},
        )
        builder.add_edge("local_model_call", "typed_validation_and_evidence")
        builder.add_edge("typed_validation_and_evidence", "human_interruption")
        builder.add_edge("human_interruption", "finish")
        builder.add_edge("finish", END)
        self._graph: Any = builder.compile()

    def classify(
        self,
        region: DocumentRegion,
        *,
        task_id: str | None = None,
        revision_id: str | None = None,
    ) -> ClassificationOutcome:
        return self.run(
            (region,),
            task_id=task_id,
            revision_id=revision_id,
        ).outcomes[0]

    def run(
        self,
        regions: tuple[DocumentRegion, ...],
        *,
        task_id: str | None = None,
        revision_id: str | None = None,
    ) -> ClassificationRun:
        if not regions:
            self.last_run = ClassificationRun(())
            return self.last_run
        inputs = tuple(
            SemanticRegionInput(
                region_id=region.id,
                file_kind=region.file_kind,
                location=region.location,
                text=region.text,
            )
            for region in regions
        )
        state = cast(
            _ClassificationState,
            self._graph.invoke(
                {
                    "regions": inputs,
                    "original_categories": {region.id: region.category for region in regions},
                }
            ),
        )
        attempts = state.get("attempts", ())
        self.last_run = ClassificationRun(
            outcomes=state["outcomes"],
            latency_ms=sum(attempt.completion.latency_ms for attempt in attempts),
            prompt_tokens=sum(attempt.completion.prompt_tokens for attempt in attempts),
            completion_tokens=sum(attempt.completion.completion_tokens for attempt in attempts),
        )
        logger.info(
            "semantic classification completed",
            extra={
                "region_count": len(regions),
                "model_region_count": sum(
                    outcome.model_assisted for outcome in self.last_run.outcomes
                ),
                "review_region_count": sum(
                    outcome.requires_human_review for outcome in self.last_run.outcomes
                ),
                "latency_ms": self.last_run.latency_ms,
                "prompt_tokens": self.last_run.prompt_tokens,
                "completion_tokens": self.last_run.completion_tokens,
            },
        )
        if (task_id is None) != (revision_id is None):
            raise ValueError("task and revision IDs must be provided together")
        if task_id is not None and revision_id is not None and self.checkpoint_store is not None:
            self.checkpoint_store.save(task_id, revision_id, self.last_run.outcomes)
        return self.last_run

    def classify_regions(
        self,
        regions: tuple[DocumentRegion, ...],
    ) -> tuple[DocumentRegion, ...]:
        run = self.run(regions)
        outcomes = {outcome.region_id: outcome for outcome in run.outcomes}
        classified: list[DocumentRegion] = []
        for region in regions:
            outcome = outcomes[region.id]
            category = outcome.category or region.category
            classified.append(
                replace(
                    region,
                    category=category,
                    semantic_reason_code=(
                        outcome.reason_code
                        if outcome.model_assisted
                        else region.semantic_reason_code
                    ),
                )
            )
        return tuple(classified)

    def _preclassify(self, state: _ClassificationState) -> dict[str, object]:
        categories = state["original_categories"]
        deterministic = tuple(
            ClassificationOutcome(
                region_id=region.region_id,
                category=categories[region.region_id],
                confidence=1,
                evidence_ids=category_evidence_for_file(
                    categories[region.region_id], region.file_kind
                ),
                requires_human_review=False,
                reason_code="deterministic_preclassification",
                model_assisted=False,
            )
            for region in state["regions"]
            if categories[region.region_id] is not ContentCategory.UNCLASSIFIED
        )
        uncertain = tuple(
            region
            for region in state["regions"]
            if categories[region.region_id] is ContentCategory.UNCLASSIFIED
        )
        return {"deterministic": deterministic, "uncertain": uncertain}

    @staticmethod
    def _route_after_preclassification(
        state: _ClassificationState,
    ) -> Literal["local_model_call", "finish"]:
        return "local_model_call" if state["uncertain"] else "finish"

    def _model_call(self, state: _ClassificationState) -> dict[str, object]:
        attempts: list[CompletionAttempt] = []
        try:
            for batch_index, regions in enumerate(self._batches(state["uncertain"])):
                region_ids = tuple(region.region_id for region in regions)
                for pass_index in range(self.consistency_passes):
                    attempts.append(
                        CompletionAttempt(
                            batch_index=batch_index,
                            pass_index=pass_index,
                            region_ids=region_ids,
                            completion=self.client.complete(regions),
                        )
                    )
            return {"attempts": tuple(attempts)}
        except LocalInferenceError:
            return {
                "attempts": tuple(attempts),
                "failure_code": "local_model_unavailable",
            }
        except Exception:
            return {
                "attempts": tuple(attempts),
                "failure_code": "controlled_local_model_failure",
            }

    def _validate(self, state: _ClassificationState) -> dict[str, object]:
        attempts = state.get("attempts", ())
        if not attempts:
            return {"validated": ()}
        by_batch: dict[int, list[CompletionAttempt]] = {}
        for attempt in attempts:
            by_batch.setdefault(attempt.batch_index, []).append(attempt)
        outcomes: list[ClassificationOutcome] = []
        invalid_output = False
        expected_batches = self._batches(state["uncertain"])
        for batch_index, regions in enumerate(expected_batches):
            batch_attempts = sorted(
                by_batch.get(batch_index, []),
                key=lambda attempt: attempt.pass_index,
            )
            if len(batch_attempts) != self.consistency_passes:
                invalid_output = True
                continue
            try:
                parsed_attempts = tuple(
                    self._validated_attempt(attempt) for attempt in batch_attempts
                )
                for region in regions:
                    items = tuple(parsed[region.region_id] for parsed in parsed_attempts)
                    evidence_is_valid = all(
                        set(item.evidence_ids).issubset(
                            category_evidence_for_file(item.category, region.file_kind)
                        )
                        for item in items
                    )
                    if not evidence_is_valid:
                        outcomes.append(
                            ClassificationOutcome(
                                region_id=region.region_id,
                                category=None,
                                confidence=0,
                                evidence_ids=("EV-GEN-002",),
                                requires_human_review=True,
                                reason_code="model_evidence_invalid",
                                model_assisted=True,
                            )
                        )
                        continue
                    categories = {item.category for item in items}
                    evidence_sets = {tuple(sorted(item.evidence_ids)) for item in items}
                    consistent = len(categories) == 1 and len(evidence_sets) == 1
                    item = items[0]
                    unresolved_category = item.category is ContentCategory.UNCLASSIFIED
                    composite_confidence = 1.0 if consistent and not unresolved_category else 0.0
                    requires_review = composite_confidence < self.min_confidence
                    outcomes.append(
                        ClassificationOutcome(
                            region_id=region.region_id,
                            category=None if requires_review else item.category,
                            confidence=composite_confidence,
                            evidence_ids=("EV-GEN-002",) if requires_review else item.evidence_ids,
                            requires_human_review=requires_review,
                            reason_code=(
                                "model_category_unresolved"
                                if unresolved_category
                                else "model_inconsistent"
                                if not consistent
                                else "semantic_model_classified"
                            ),
                            model_assisted=True,
                        )
                    )
            except (ValidationError, ValueError, KeyError):
                invalid_output = True
        update: dict[str, object] = {"validated": tuple(outcomes)}
        if invalid_output and "failure_code" not in state:
            update["failure_code"] = "model_output_invalid"
        return update

    @staticmethod
    def _validated_attempt(
        attempt: CompletionAttempt,
    ) -> dict[str, ModelClassification]:
        batch = ClassificationBatch.model_validate_json(attempt.completion.content)
        returned_ids = tuple(item.region_id for item in batch.classifications)
        if len(set(returned_ids)) != len(returned_ids) or set(returned_ids) != set(
            attempt.region_ids
        ):
            raise ValueError("model region IDs did not match the stable input IDs")
        return {item.region_id: item for item in batch.classifications}

    def _batches(
        self,
        regions: tuple[SemanticRegionInput, ...],
    ) -> tuple[tuple[SemanticRegionInput, ...], ...]:
        by_file_kind: dict[FileKind, list[SemanticRegionInput]] = {}
        for region in regions:
            by_file_kind.setdefault(region.file_kind, []).append(region)
        return tuple(
            tuple(file_regions[start : start + self.batch_size])
            for file_regions in by_file_kind.values()
            for start in range(0, len(file_regions), self.batch_size)
        )

    @staticmethod
    def _human_review(state: _ClassificationState) -> dict[str, object]:
        validated = state.get("validated", ())
        resolved_ids = {outcome.region_id for outcome in validated}
        reason_code = state.get("failure_code", "semantic_review_required")
        unresolved = tuple(
            ClassificationOutcome(
                region_id=region.region_id,
                category=None,
                confidence=0,
                evidence_ids=("EV-GEN-002",),
                requires_human_review=True,
                reason_code=reason_code,
                model_assisted=True,
            )
            for region in state["uncertain"]
            if region.region_id not in resolved_ids
        )
        return {"validated": validated + unresolved}

    @staticmethod
    def _finish(state: _ClassificationState) -> dict[str, object]:
        by_id = {
            outcome.region_id: outcome
            for outcome in state.get("deterministic", ()) + state.get("validated", ())
        }
        return {"outcomes": tuple(by_id[region.region_id] for region in state["regions"])}


__all__ = ["SemanticClassificationGraph"]
