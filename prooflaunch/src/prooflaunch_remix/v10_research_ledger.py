from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Mapping, Sequence
from urllib.parse import urlparse

from .v10_contracts import V10ContractError


class EvidenceStrength(str, Enum):
    PRIMARY_METADATA = "primary_metadata"
    PAPER_INSPECTED = "paper_inspected"
    CODE_INSPECTED = "code_inspected"
    REPRODUCED = "reproduced"
    RADEON_OBSERVED = "radeon_observed"


class ResearchDisposition(str, Enum):
    DIRECT_ADOPT = "direct_adopt"
    EQUIVALENT_SIMPLIFICATION = "equivalent_simplification"
    ABLATION_ONLY = "ablation_only"
    INFEASIBLE_CURRENT_BUDGET = "infeasible_current_budget"


class MetricDirection(str, Enum):
    MIN = "min"
    MAX = "max"


@dataclass(frozen=True)
class MetricGate:
    name: str
    direction: MetricDirection
    threshold: float
    objective: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip() or not math.isfinite(self.threshold):
            raise V10ContractError("research metric requires a name and finite threshold")
        if not self.objective:
            raise V10ContractError("subjective-only research metrics are forbidden")


@dataclass(frozen=True)
class StudyBudget:
    gpu_minutes: int
    wall_minutes: int
    external_api_usd: float
    maximum_examples: int

    def __post_init__(self) -> None:
        if min(self.gpu_minutes, self.wall_minutes, self.maximum_examples) <= 0:
            raise V10ContractError("research budgets must be finite and positive")
        if not math.isfinite(self.external_api_usd) or self.external_api_usd < 0:
            raise V10ContractError("external API budget must be finite and non-negative")


@dataclass(frozen=True)
class ResearchSource:
    research_id: str
    todo_id: str
    topic: str
    title: str
    primary_url: str
    version_date: str
    official_implementation_url: str | None
    implementation_revision: str | None
    implementation_status: str
    hardware_scale: str
    original_task_scope: str
    known_failure_modes: tuple[str, ...]
    mechanism: str
    local_transfer: str
    evidence_strength: EvidenceStrength

    def __post_init__(self) -> None:
        required = (
            self.research_id,
            self.todo_id,
            self.topic,
            self.title,
            self.version_date,
            self.implementation_status,
            self.hardware_scale,
            self.original_task_scope,
            self.mechanism,
            self.local_transfer,
        )
        if not all(item.strip() for item in required):
            raise V10ContractError("research-source metadata is incomplete")
        if len(self.todo_id) != 4 or not self.todo_id.isdigit():
            raise V10ContractError("research source requires a four-digit TODO id")
        try:
            date.fromisoformat(self.version_date)
        except ValueError as exc:
            raise V10ContractError("research version date must be ISO-8601") from exc
        parsed = urlparse(self.primary_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise V10ContractError("research sources require a primary HTTPS locator")
        if self.official_implementation_url:
            code = urlparse(self.official_implementation_url)
            if code.scheme != "https" or not code.hostname:
                raise V10ContractError("official implementation URL must be HTTPS")
            if not self.implementation_revision:
                raise V10ContractError("published implementations require a frozen revision")
        elif self.implementation_revision:
            raise V10ContractError("implementation revision cannot exist without a URL")
        if not self.known_failure_modes:
            raise V10ContractError("every research source requires a known failure mode")


@dataclass(frozen=True)
class FalsifiableStudy:
    research_id: str
    hypothesis: str
    controls: tuple[str, ...]
    metrics: tuple[MetricGate, ...]
    budget: StudyBudget
    stop_condition: str
    disposition: ResearchDisposition
    transferability_score: int
    single_card_score: int
    commercial_value_score: int

    def __post_init__(self) -> None:
        if not self.research_id.strip() or not self.hypothesis.strip():
            raise V10ContractError("falsifiable study requires identity and hypothesis")
        if len(self.controls) < 1 or len(self.metrics) < 2:
            raise V10ContractError("every study requires a control and at least two metrics")
        if not self.stop_condition.strip():
            raise V10ContractError("every study requires a stop condition")
        scores = (
            self.transferability_score,
            self.single_card_score,
            self.commercial_value_score,
        )
        if any(score < 0 or score > 5 for score in scores):
            raise V10ContractError("research utility scores must be in [0, 5]")

    @property
    def queue_score(self) -> int:
        return (
            2 * self.transferability_score
            + 2 * self.single_card_score
            + self.commercial_value_score
        )


@dataclass(frozen=True)
class ExperimentReceipt:
    research_id: str
    run_id: str
    evidence_strength: EvidenceStrength
    observed_metrics: Mapping[str, float]
    gates_passed: bool
    falsified: bool
    evidence_locator: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.research_id, self.run_id, self.evidence_locator)
        ):
            raise V10ContractError("experiment receipt identity is incomplete")
        if self.evidence_strength in {
            EvidenceStrength.PRIMARY_METADATA,
            EvidenceStrength.PAPER_INSPECTED,
            EvidenceStrength.CODE_INSPECTED,
        }:
            raise V10ContractError("an experiment receipt must represent an executed run")
        if not self.observed_metrics:
            raise V10ContractError("executed research requires observed metrics")
        if any(not math.isfinite(value) for value in self.observed_metrics.values()):
            raise V10ContractError("observed metrics must be finite")
        if self.gates_passed and self.falsified:
            raise V10ContractError("a receipt cannot both pass and falsify its hypothesis")


def validate_registry(
    sources: Sequence[ResearchSource], studies: Sequence[FalsifiableStudy]
) -> None:
    if len(sources) != 25:
        raise V10ContractError("Research Ledger V1 requires exactly 25 deconstructions")
    source_ids = [item.research_id for item in sources]
    todo_ids = [item.todo_id for item in sources]
    if len(set(source_ids)) != len(source_ids) or len(set(todo_ids)) != len(todo_ids):
        raise V10ContractError("research and TODO identities must be unique")
    if todo_ids != [f"{value:04d}" for value in range(107, 132)]:
        raise V10ContractError("research deconstructions must preserve TODO 0107-0131 order")
    study_ids = [item.research_id for item in studies]
    if study_ids != source_ids:
        raise V10ContractError("every source requires one in-order falsifiable study")


def research_queue(studies: Sequence[FalsifiableStudy]) -> tuple[FalsifiableStudy, ...]:
    return tuple(sorted(studies, key=lambda item: (-item.queue_score, item.research_id)))


def result_leaderboard(
    studies: Sequence[FalsifiableStudy], receipts: Sequence[ExperimentReceipt]
) -> tuple[tuple[FalsifiableStudy, ExperimentReceipt], ...]:
    by_id = {item.research_id: item for item in studies}
    if len(by_id) != len(studies):
        raise V10ContractError("study identities must be unique")
    admitted = []
    for receipt in receipts:
        study = by_id.get(receipt.research_id)
        if study is None:
            raise V10ContractError("receipt references an unknown research study")
        if receipt.gates_passed and not receipt.falsified:
            admitted.append((study, receipt))
    return tuple(sorted(admitted, key=lambda row: (-row[0].queue_score, row[0].research_id)))


def negative_experiments(
    receipts: Sequence[ExperimentReceipt],
) -> tuple[ExperimentReceipt, ...]:
    return tuple(item for item in receipts if item.falsified or not item.gates_passed)


def innovation_combinations(
    studies: Sequence[FalsifiableStudy],
    receipts: Sequence[ExperimentReceipt],
    *,
    maximum_components: int = 3,
) -> tuple[str, ...]:
    if maximum_components <= 0:
        raise V10ContractError("innovation selector requires a positive component cap")
    eligible = result_leaderboard(studies, receipts)
    return tuple(study.research_id for study, _ in eligible[:maximum_components])
