from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .files import atomic_write_text
from .v10_contracts import (
    BreakthroughBetSpec,
    BreakthroughDecision,
    BreakthroughEvidenceBundle,
    BreakthroughMeasurement,
    EvidenceAxis,
    EvidenceClass,
    EvidencePointer,
    V10ContractError,
    stable_digest,
)


MATRIX_SCHEMA = "ProofLaunchBreakthroughMatrixV10"
FROZEN_BASELINES = (
    "cortex-x-v9",
    "deterministic-langgraph",
    "qwen-agent-tool-workflow",
    "agent-r1-step-agent",
    "fixed-4a-agency-pipeline",
)


@dataclass(frozen=True)
class BreakthroughDefinition:
    bet_id: str
    workstream_id: int
    todo_start: str
    todo_end: str
    title: str
    hypothesis: str
    implementation_files: tuple[str, ...]
    gpu_budget_hours: float


BREAKTHROUGHS = (
    BreakthroughDefinition(
        "BT25",
        25,
        "1201",
        "1225",
        "Causal Market Digital Twin",
        "A source-isolated causal twin improves future intervention ranking over correlation while remaining calibrated under negative controls.",
        ("src/prooflaunch_remix/v10_intelligence.py",),
        4,
    ),
    BreakthroughDefinition(
        "BT26",
        26,
        "1226",
        "1250",
        "Action-Conditioned Campaign World Model",
        "Bounded action-conditioned search improves strategy quality without inventing feedback or exceeding latency and risk budgets.",
        ("src/prooflaunch_remix/v10_intelligence.py",),
        4,
    ),
    BreakthroughDefinition(
        "BT27",
        27,
        "1251",
        "1275",
        "Campaign Genome",
        "A typed, mutable campaign genome increases cross-channel coherence and controllable diversity while preserving identity.",
        ("src/prooflaunch_remix/v10_intelligence.py",),
        3,
    ),
    BreakthroughDefinition(
        "BT28",
        28,
        "1276",
        "1300",
        "Proof-Carrying Creative",
        "Content-addressed claim, region, transform, and approval graphs eliminate critical unsupported claims and reduce review time.",
        (
            "src/prooflaunch_remix/v10_contracts.py",
            "src/prooflaunch_remix/v10_creative.py",
        ),
        3,
    ),
    BreakthroughDefinition(
        "BT29",
        29,
        "1301",
        "1325",
        "Dynamic Agency Designer",
        "A bounded, single-supervisor agency topology improves completion quality enough to cover its coordination cost.",
        ("src/prooflaunch_remix/v10_agency.py",),
        3,
    ),
    BreakthroughDefinition(
        "BT30",
        30,
        "1326",
        "1350",
        "Role-Conditioned Sparse Adapter Routing",
        "Top-two role adapters move the quality-cost Pareto frontier without routing collapse or general-capability regression.",
        (
            "src/prooflaunch_remix/v10_agency.py",
            "src/prooflaunch_remix/v10_training.py",
        ),
        4,
    ),
    BreakthroughDefinition(
        "BT31",
        31,
        "1351",
        "1375",
        "Agency Taste and Rich Feedback",
        "Calibrated, region-grounded rich feedback raises independent 4A preference and targeted repair quality over scalar reward.",
        (
            "src/prooflaunch_remix/v10_creative.py",
            "src/prooflaunch_remix/v10_training.py",
        ),
        3,
    ),
    BreakthroughDefinition(
        "BT32",
        32,
        "1376",
        "1400",
        "Region-Time Quality Tensor and Repair",
        "Bounded region-time repair improves 4K craft metrics and repair efficiency while preserving product and brand identity.",
        ("src/prooflaunch_remix/v10_creative.py",),
        4,
    ),
    BreakthroughDefinition(
        "BT33",
        33,
        "1401",
        "1425",
        "Task-Focused Brand Memory",
        "Freshness-, approval-, and conflict-aware task memory produces positive cross-campaign transfer without contamination.",
        ("src/prooflaunch_remix/v10_agency.py",),
        3,
    ),
    BreakthroughDefinition(
        "BT34",
        34,
        "1426",
        "1450",
        "Outcome-Aware Test-Time Controller",
        "Risk- and evidence-aware compute allocation improves quality per GPU hour without unauthorized budget overruns.",
        ("src/prooflaunch_remix/v10_agency.py",),
        3,
    ),
    BreakthroughDefinition(
        "BT35",
        35,
        "1451",
        "1475",
        "Causal Experiment Autopilot",
        "Quality-gated randomization, SRM detection, and variance reduction recover treatment effects without false business attribution.",
        (
            "src/prooflaunch_remix/v10_contracts.py",
            "src/prooflaunch_remix/v10_intelligence.py",
        ),
        4,
    ),
    BreakthroughDefinition(
        "BT36",
        36,
        "1476",
        "1500",
        "2027 Campaign Operating Space",
        "A persistent object workspace reduces end-to-end GTM task time and cognitive load while preserving auditability and recovery.",
        (
            "src/prooflaunch_remix/v10_creative.py",
            "src/prooflaunch_remix/workflow.py",
            "src/prooflaunch_remix/runtime.py",
        ),
        2,
    ),
)


def _pointer(
    root: Path,
    relative_path: str,
    *,
    axis: EvidenceAxis,
    evidence_class: EvidenceClass,
    note: str,
) -> EvidencePointer:
    path = root / relative_path
    if not path.is_file():
        raise V10ContractError(f"breakthrough evidence is missing: {relative_path}")
    return EvidencePointer(
        axis=axis,
        locator=relative_path,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        evidence_class=evidence_class,
        note=note,
    )


def _pointer_dict(pointer: EvidencePointer) -> dict[str, str]:
    return pointer.to_dict()


def _measurement_dict(
    measurement: BreakthroughMeasurement,
) -> dict[str, Any]:
    return {
        "metric": measurement.metric,
        "actual": measurement.actual,
        "threshold": measurement.threshold,
        "higher_is_better": measurement.higher_is_better,
        "passed": measurement.passed,
        "evidence": _pointer_dict(measurement.evidence),
    }


def _bundle_dict(bundle: BreakthroughEvidenceBundle) -> dict[str, Any]:
    return {
        "schema": bundle.schema,
        "bet_id": bundle.bet_id,
        "code": [_pointer_dict(item) for item in bundle.code],
        "configuration": [
            _pointer_dict(item) for item in bundle.configuration
        ],
        "data_rights": [_pointer_dict(item) for item in bundle.data_rights],
        "logs": [_pointer_dict(item) for item in bundle.logs],
        "ablations": [_pointer_dict(item) for item in bundle.ablations],
        "radeon_traces": [
            _pointer_dict(item) for item in bundle.radeon_traces
        ],
        "product_tests": [
            _pointer_dict(item) for item in bundle.product_tests
        ],
        "effect_tests": [
            _pointer_dict(item) for item in bundle.effect_tests
        ],
        "negative_results": [
            _pointer_dict(item) for item in bundle.negative_results
        ],
        "insufficient_sections": list(bundle.missing_sections()),
    }


def build_breakthrough_matrix(
    project_root: str | Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    report_path = root / "evidence/v10/local-test-report.json"
    if not report_path.is_file():
        raise V10ContractError(
            "run scripts/run_v10_local_suite.py before building the matrix"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    local_suite_passed = report.get("status") == "passed"
    if len(BREAKTHROUGHS) != 12 or sum(
        item.gpu_budget_hours for item in BREAKTHROUGHS
    ) > 40:
        raise V10ContractError(
            "the V10 matrix requires exactly 12 bets within 40 GPU-hours"
        )

    common_configuration = _pointer(
        root,
        "config/cortex_x_v10_training_plan.json",
        axis=EvidenceAxis.DISTILLATION,
        evidence_class=EvidenceClass.OBSERVED,
        note="Versioned six-stage single-Radeon execution plan exists; execution is separately gated.",
    )
    rights_contract = _pointer(
        root,
        "config/cortex_x_v10_training_plan.json",
        axis=EvidenceAxis.ACADEMIC,
        evidence_class=EvidenceClass.PROXY,
        note="Rights and split schema is defined, but no audited licensed corpus manifest has been supplied.",
    )
    local_log = _pointer(
        root,
        "evidence/v10/local-test-report.json",
        axis=EvidenceAxis.EVIDENCE,
        evidence_class=EvidenceClass.OBSERVED,
        note="Observed local unit-suite execution receipt; it is not Radeon, human, or production evidence.",
    )
    ablation_plan = _pointer(
        root,
        "tests/test_v10_breakthroughs.py",
        axis=EvidenceAxis.EVIDENCE,
        evidence_class=EvidenceClass.PROXY,
        note="Negative controls and deterministic contract fixtures exist; frozen-baseline ablation results are not yet present.",
    )
    radeon_plan = _pointer(
        root,
        "notebooks/prooflaunch_cortex_x_v10_radeon.ipynb",
        axis=EvidenceAxis.TECHNICAL,
        evidence_class=EvidenceClass.PROXY,
        note="Fail-closed Radeon notebook is packaged but has no successful V10 kernel execution trace.",
    )
    product_proxy = _pointer(
        root,
        "tests/test_v10_breakthroughs.py",
        axis=EvidenceAxis.PRODUCT,
        evidence_class=EvidenceClass.PROXY,
        note="Local product-mechanism fixtures pass or fail deterministically; independent 4A task testing is absent.",
    )
    effect_proxy = _pointer(
        root,
        "tests/test_v10_breakthroughs.py",
        axis=EvidenceAxis.EFFECT,
        evidence_class=EvidenceClass.PROXY,
        note="Synthetic and contract tests are explicitly proxy evidence; frozen blind or authorized causal outcomes are absent.",
    )

    entries: list[dict[str, Any]] = []
    verdict_counts = {"promote": 0, "hold": 0, "reject": 0}
    for definition in BREAKTHROUGHS:
        code = tuple(
            _pointer(
                root,
                file_path,
                axis=EvidenceAxis.INNOVATION,
                evidence_class=EvidenceClass.OBSERVED,
                note=(
                    f"Local deterministic reference implementation for "
                    f"{definition.bet_id}; no external superiority is implied."
                ),
            )
            for file_path in definition.implementation_files
        )
        bundle = BreakthroughEvidenceBundle(
            bet_id=definition.bet_id,
            code=code,
            configuration=(common_configuration,),
            data_rights=(rights_contract,),
            logs=(local_log,),
            ablations=(ablation_plan,),
            radeon_traces=(radeon_plan,),
            product_tests=(product_proxy,),
            effect_tests=(effect_proxy,),
        )
        spec = BreakthroughBetSpec(
            bet_id=definition.bet_id,
            hypothesis=definition.hypothesis,
            baseline_ids=FROZEN_BASELINES,
            success_thresholds={
                "local_contract_suite": 1.0,
                "independent_product_validation": 1.0,
                "frozen_effect_validation": 1.0,
            },
            gpu_budget_hours=definition.gpu_budget_hours,
            elimination_rules=(
                "rights or safety gate fails",
                "general multimodal regression exceeds 0.5%",
                "Radeon reproduction fails",
                "technical, product, or effect evidence is absent",
            ),
            evidence_root=f"evidence/v10/breakthroughs/{definition.bet_id.lower()}",
        )
        technical = (
            BreakthroughMeasurement(
                "local_contract_suite",
                1.0 if local_suite_passed else 0.0,
                1.0,
                True,
                local_log,
            ),
        )
        product = (
            BreakthroughMeasurement(
                "independent_product_validation",
                0.0,
                1.0,
                True,
                product_proxy,
            ),
        )
        effect = (
            BreakthroughMeasurement(
                "frozen_effect_validation",
                0.0,
                1.0,
                True,
                effect_proxy,
            ),
        )
        decision = BreakthroughDecision.evaluate(
            spec,
            bundle,
            technical=technical,
            product=product,
            effect=effect,
        )
        verdict_counts[decision.verdict.value] += 1
        entries.append(
            {
                "bet_id": definition.bet_id,
                "workstream_id": definition.workstream_id,
                "todo_range": [
                    definition.todo_start,
                    definition.todo_end,
                ],
                "title": definition.title,
                "spec": {
                    "hypothesis": spec.hypothesis,
                    "baseline_ids": list(spec.baseline_ids),
                    "success_thresholds": dict(spec.success_thresholds),
                    "gpu_budget_hours": spec.gpu_budget_hours,
                    "elimination_rules": list(spec.elimination_rules),
                    "evidence_root": spec.evidence_root,
                },
                "evidence_bundle": _bundle_dict(bundle),
                "measurements": {
                    "technical": [
                        _measurement_dict(item) for item in technical
                    ],
                    "product": [
                        _measurement_dict(item) for item in product
                    ],
                    "effect": [_measurement_dict(item) for item in effect],
                },
                "decision": {
                    "verdict": decision.verdict.value,
                    "reasons": list(decision.reasons),
                    "decided_at": decision.decided_at,
                },
            }
        )

    payload: dict[str, Any] = {
        "schema": MATRIX_SCHEMA,
        "generated_at": generated_at
        or datetime.now(timezone.utc).isoformat(),
        "source_program": "evidence/v10/program-manifest.json",
        "frozen_baselines": list(FROZEN_BASELINES),
        "gpu_budget_hours": {
            "maximum": 40,
            "allocated": sum(
                item.gpu_budget_hours for item in BREAKTHROUGHS
            ),
            "executed": 0,
        },
        "summary": {
            "bet_count": len(entries),
            "verdict_counts": verdict_counts,
            "all_have_evidence_bundles": True,
            "all_have_radeon_execution": False,
            "all_have_independent_product_tests": False,
            "all_have_effect_validation": False,
            "promotion_floor": 3,
            "promotion_floor_met": verdict_counts["promote"] >= 3,
        },
        "bets": entries,
        "truth_boundary": (
            "Local deterministic implementations and tests are observed "
            "engineering evidence only. Planned corpora, notebook presence, "
            "synthetic fixtures, and self-evaluation are proxy evidence. No bet "
            "is promoted without audited data rights, executed ablations, "
            "Radeon traces, independent 4A product tests, and frozen effect "
            "validation."
        ),
    }
    payload["content_sha256"] = stable_digest(payload)
    return payload


def write_breakthrough_matrix(
    project_root: str | Path,
    output_path: str | Path,
) -> Mapping[str, Any]:
    payload = build_breakthrough_matrix(project_root)
    target = Path(output_path)
    if not target.is_absolute():
        target = Path(project_root) / target
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        target,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    return payload
