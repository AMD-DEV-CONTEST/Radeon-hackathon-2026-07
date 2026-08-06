from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable, Mapping, Sequence


class ExcellenceGateError(ValueError):
    pass


class EvidenceFacet(str, Enum):
    AUTHORITATIVE_SOURCE = "authoritative_source"
    ARTIFACT_HASH = "artifact_hash"
    POSITIVE_TEST = "positive_test"
    NEGATIVE_TEST = "negative_test"
    STOP_RULE = "stop_rule"
    ROLLBACK = "rollback"
    TRUTH_BOUNDARY = "truth_boundary"
    IMMUTABLE_REVISION = "immutable_revision"
    DATA_RIGHTS = "data_rights"
    FROZEN_BASELINE = "frozen_baseline"
    ABLATION = "ablation"
    NEGATIVE_CONTROL = "negative_control"
    FALSIFIER = "falsifier"
    MULTI_SEED = "multi_seed"
    CALIBRATION = "calibration"
    MULTIMODAL_RETENTION = "multimodal_retention"
    RADEON_LOCAL_INFERENCE = "radeon_local_inference"
    RADEON_PERFORMANCE = "radeon_performance"
    CLARITY_STABILITY_DIVERSITY = "clarity_stability_diversity"
    FOUR_K_OUTPUT = "four_k_output"
    BLIND_4A_REVIEW = "blind_4a_review"
    HUMAN_APPROVAL = "human_approval"
    MULTI_GPU_PROGRAM_BINDING = "multi_gpu_program_binding"
    MULTI_GPU_RUNTIME = "multi_gpu_runtime"
    MULTI_GPU_EQUIVALENCE = "multi_gpu_equivalence"
    MULTI_GPU_EFFICIENCY = "multi_gpu_efficiency"
    OFFICIAL_PROGRAM_COMPLIANCE = "official_program_compliance"
    OFFICIAL_ELIGIBILITY = "official_eligibility"
    ENGLISH_MATERIALS = "english_materials"
    OFFICIAL_DELIVERABLES = "official_deliverables"
    OFFICIAL_FORK_PR = "official_fork_pr"


UNIVERSAL_FACETS = (
    EvidenceFacet.AUTHORITATIVE_SOURCE,
    EvidenceFacet.ARTIFACT_HASH,
    EvidenceFacet.POSITIVE_TEST,
    EvidenceFacet.NEGATIVE_TEST,
    EvidenceFacet.STOP_RULE,
    EvidenceFacet.ROLLBACK,
    EvidenceFacet.TRUTH_BOUNDARY,
    EvidenceFacet.MULTI_GPU_PROGRAM_BINDING,
)

RESEARCH_WORKSTREAMS = frozenset(
    {3, 5, 6, 7, 8, 15, 16, 17, *range(25, 37)}
)
TRAINING_WORKSTREAMS = frozenset(
    {4, 7, *range(9, 19), 21, *range(30, 35)}
)
MULTIMODAL_PRODUCT_WORKSTREAMS = frozenset(
    {5, 8, *range(18, 22), *range(24, 37)}
)
FOUR_K_WORKSTREAMS = frozenset({19, 20, 21, 24, 27, 28, 31, 32, 36})
SUBMISSION_WORKSTREAMS = frozenset({1, 24})
DIRECT_MULTI_GPU_WORKSTREAMS = frozenset(
    {
        3,
        4,
        5,
        7,
        8,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        23,
        25,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
    }
)

EXTERNAL_ONLY_FACETS = frozenset(
    {
        EvidenceFacet.MULTI_SEED,
        EvidenceFacet.MULTIMODAL_RETENTION,
        EvidenceFacet.RADEON_LOCAL_INFERENCE,
        EvidenceFacet.RADEON_PERFORMANCE,
        EvidenceFacet.CLARITY_STABILITY_DIVERSITY,
        EvidenceFacet.FOUR_K_OUTPUT,
        EvidenceFacet.BLIND_4A_REVIEW,
        EvidenceFacet.HUMAN_APPROVAL,
        EvidenceFacet.MULTI_GPU_RUNTIME,
        EvidenceFacet.MULTI_GPU_EQUIVALENCE,
        EvidenceFacet.MULTI_GPU_EFFICIENCY,
        EvidenceFacet.OFFICIAL_PROGRAM_COMPLIANCE,
        EvidenceFacet.OFFICIAL_ELIGIBILITY,
        EvidenceFacet.OFFICIAL_DELIVERABLES,
        EvidenceFacet.OFFICIAL_FORK_PR,
    }
)


@dataclass(frozen=True)
class TodoExcellenceRequirement:
    todo_id: str
    workstream_id: int
    official_floor: tuple[EvidenceFacet, ...]
    overdelivery_gate: tuple[EvidenceFacet, ...]

    @property
    def required_facets(self) -> tuple[EvidenceFacet, ...]:
        return tuple(
            dict.fromkeys((*self.official_floor, *self.overdelivery_gate))
        )

    def to_dict(self) -> dict:
        return {
            "todo_id": self.todo_id,
            "workstream_id": self.workstream_id,
            "official_floor": [item.value for item in self.official_floor],
            "overdelivery_gate": [
                item.value for item in self.overdelivery_gate
            ],
            "required_facets": [item.value for item in self.required_facets],
        }


@dataclass(frozen=True)
class FacetEvidence:
    facet: EvidenceFacet
    observed: bool
    locator: str
    sha256: str
    evidence_class: str
    proxy: bool = False

    def __post_init__(self) -> None:
        if self.observed and (not self.locator.strip() or len(self.sha256) != 64):
            raise ExcellenceGateError(
                "observed evidence requires a locator and 64-character SHA-256"
            )


@dataclass(frozen=True)
class TodoExcellenceReport:
    todo_id: str
    passed: bool
    passed_facets: tuple[str, ...]
    missing_facets: tuple[str, ...]
    rejected_proxy_facets: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def requirement_for(todo_id: str, workstream_id: int) -> TodoExcellenceRequirement:
    if len(todo_id) != 4 or not todo_id.isdigit():
        raise ExcellenceGateError("todo_id must be four digits")
    if workstream_id < 1 or workstream_id > 36:
        raise ExcellenceGateError("workstream_id must be in [1, 36]")

    official: list[EvidenceFacet] = [
        EvidenceFacet.OFFICIAL_PROGRAM_COMPLIANCE
    ]
    overdelivery = list(UNIVERSAL_FACETS)

    if workstream_id in SUBMISSION_WORKSTREAMS:
        official.extend(
            (
                EvidenceFacet.OFFICIAL_ELIGIBILITY,
                EvidenceFacet.ENGLISH_MATERIALS,
                EvidenceFacet.OFFICIAL_DELIVERABLES,
                EvidenceFacet.OFFICIAL_FORK_PR,
                EvidenceFacet.RADEON_LOCAL_INFERENCE,
                EvidenceFacet.CLARITY_STABILITY_DIVERSITY,
            )
        )
    if workstream_id in RESEARCH_WORKSTREAMS:
        overdelivery.extend(
            (
                EvidenceFacet.FROZEN_BASELINE,
                EvidenceFacet.ABLATION,
                EvidenceFacet.NEGATIVE_CONTROL,
                EvidenceFacet.FALSIFIER,
            )
        )
    if workstream_id in TRAINING_WORKSTREAMS:
        overdelivery.extend(
            (
                EvidenceFacet.IMMUTABLE_REVISION,
                EvidenceFacet.DATA_RIGHTS,
                EvidenceFacet.FROZEN_BASELINE,
                EvidenceFacet.ABLATION,
                EvidenceFacet.NEGATIVE_CONTROL,
                EvidenceFacet.MULTI_SEED,
                EvidenceFacet.CALIBRATION,
                EvidenceFacet.MULTIMODAL_RETENTION,
                EvidenceFacet.RADEON_PERFORMANCE,
            )
        )
    if workstream_id in MULTIMODAL_PRODUCT_WORKSTREAMS:
        overdelivery.extend(
            (
                EvidenceFacet.RADEON_LOCAL_INFERENCE,
                EvidenceFacet.RADEON_PERFORMANCE,
                EvidenceFacet.CLARITY_STABILITY_DIVERSITY,
                EvidenceFacet.BLIND_4A_REVIEW,
                EvidenceFacet.HUMAN_APPROVAL,
            )
        )
    if workstream_id in FOUR_K_WORKSTREAMS:
        overdelivery.append(EvidenceFacet.FOUR_K_OUTPUT)
    if workstream_id in DIRECT_MULTI_GPU_WORKSTREAMS:
        overdelivery.extend(
            (
                EvidenceFacet.MULTI_GPU_RUNTIME,
                EvidenceFacet.MULTI_GPU_EQUIVALENCE,
                EvidenceFacet.MULTI_GPU_EFFICIENCY,
            )
        )

    return TodoExcellenceRequirement(
        todo_id=todo_id,
        workstream_id=workstream_id,
        official_floor=tuple(dict.fromkeys(official)),
        overdelivery_gate=tuple(dict.fromkeys(overdelivery)),
    )


def requirements_for_program(
    todos: Sequence[Mapping[str, object]],
) -> tuple[TodoExcellenceRequirement, ...]:
    requirements = tuple(
        requirement_for(
            str(todo["todo_id"]),
            int(todo["workstream_id"]),
        )
        for todo in todos
    )
    ids = [item.todo_id for item in requirements]
    if len(ids) != 1500 or len(set(ids)) != 1500:
        raise ExcellenceGateError(
            "the excellence gate requires exactly 1,500 unique TODOs"
        )
    if ids != [f"{index:04d}" for index in range(1, 1501)]:
        raise ExcellenceGateError("TODOs must be ordered 0001 through 1500")
    return requirements


def evaluate_requirement(
    requirement: TodoExcellenceRequirement,
    evidence: Iterable[FacetEvidence],
) -> TodoExcellenceReport:
    evidence_by_facet = {item.facet: item for item in evidence}
    passed: list[str] = []
    missing: list[str] = []
    rejected_proxy: list[str] = []
    for facet in requirement.required_facets:
        item = evidence_by_facet.get(facet)
        if item is None or not item.observed:
            missing.append(facet.value)
            continue
        if item.proxy and facet in EXTERNAL_ONLY_FACETS:
            rejected_proxy.append(facet.value)
            continue
        passed.append(facet.value)
    return TodoExcellenceReport(
        todo_id=requirement.todo_id,
        passed=not missing and not rejected_proxy,
        passed_facets=tuple(passed),
        missing_facets=tuple(missing),
        rejected_proxy_facets=tuple(rejected_proxy),
    )
