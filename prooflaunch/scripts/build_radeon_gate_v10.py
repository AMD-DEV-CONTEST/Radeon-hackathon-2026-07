#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "notebooks" / "prooflaunch_radeon_gate_v7.ipynb"
DESTINATION = ROOT / "notebooks" / "prooflaunch_cortex_x_v10_radeon.ipynb"


def source_of(cell: dict) -> str:
    source = cell.get("source", [])
    return "".join(source) if isinstance(source, list) else str(source)


def set_source(cell: dict, value: str) -> None:
    cell["source"] = value.splitlines(keepends=True)


def markdown(value: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": value.splitlines(keepends=True),
    }


def code(value: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": value.splitlines(keepends=True),
    }


def main() -> None:
    notebook = json.loads(SOURCE.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        updated = (
            source_of(cell)
            .replace(
                "ProofLaunch Radeon Gate V7",
                "ProofLaunch Cortex-X V10 Radeon Gate",
            )
            .replace(
                "prooflaunch-radeon-v7",
                "prooflaunch-radeon-v10",
            )
        )
        set_source(cell, updated)

    notebook["cells"].extend(
        [
            markdown(
                """## 6. Official-first external teacher and Agent route

Every external model or Agent inference call first uses the official AMD
Radeon Token Factory endpoint. If all public official models fail with an
availability, rate-limit, server, or response-contract error, an approved
Fireworks route may take over for training-data generation, teacher
distillation, evaluation, or development Agent work.

Credentials come only from environment variables. The receipt contains no
credential, prompt, or output. This external route is never eligible as local
Radeon execution or competition-core benchmark evidence.

The current Token Factory account is capped at $10 per Asia/Shanghai daily
window and 30 RPM. The client keeps 24 RPM headroom, a 4,096-token request
ceiling, six attempts per logical completion, and a $0.0001 settlement buffer.
KV cache hits are optional provider telemetry, not a competition requirement.
"""
            ),
            code(
                """import hashlib
import os

from prooflaunch_remix.inference_gateway import (
    InferenceGatewayCallError,
    InferenceScope,
    OpenAICompatibleThirdPartyClient,
    ResilientInferenceGateway,
    load_third_party_provider_specs,
)
from prooflaunch_remix.tokenfactory import (
    TOKEN_FACTORY_API_KEY_ENV,
    TokenFactoryClient,
    TokenFactoryConfigurationError,
    tokenfactory_policy,
)

online_policy = tokenfactory_policy()
assert online_policy["competition_core_path"] == "local_radeon_only"
assert online_policy["external_inference_priority"][0] == (
    "amd_radeon_token_factory"
)
assert online_policy["quota"]["daily_budget_usd"] == 10.0
assert online_policy["quota"]["provider_rpm_limit"] == 30
assert online_policy["quota"]["client_rpm_limit"] == 24
assert online_policy["quota"]["daily_reserve_usd"] == 0.0001
assert online_policy["quota"]["max_tokens_per_request"] == 4096
route_receipt_path = (
    repo / "evidence" / "radeon" / "tokenfactory-route-receipt.json"
)
route_receipt_path.parent.mkdir(parents=True, exist_ok=True)

if not os.environ.get(TOKEN_FACTORY_API_KEY_ENV):
    route_receipt = {
        "schema": "ProofLaunchResilientInferenceGatewayV1",
        "status": "blocked",
        "reason": f"missing {TOKEN_FACTORY_API_KEY_ENV}",
        "credential": {
            "source": TOKEN_FACTORY_API_KEY_ENV,
            "persisted": False,
            "redacted": True,
        },
        "competition_core_eligible": False,
    }
else:
    fallback_specs = load_third_party_provider_specs(
        repo / "config" / "fireworks-fallback.example.json"
    )
    gateway = ResilientInferenceGateway(
        official_client=TokenFactoryClient(),
        third_party_clients=tuple(
            OpenAICompatibleThirdPartyClient(spec)
            for spec in fallback_specs
        ),
    )
    try:
        route_result = gateway.complete(
            [
                {
                    "role": "user",
                    "content": (
                        "Return exactly TOKENFACTORY_ROUTE_OK. "
                        "Do not add any other text."
                    ),
                }
            ],
            scope=InferenceScope.EVALUATION,
            purpose="Radeon Notebook external-route contract probe",
            max_tokens=32,
            temperature=0,
        )
        route_receipt = {
            **route_result.receipt,
            "response_content_sha256": hashlib.sha256(
                route_result.content.encode("utf-8")
            ).hexdigest(),
            "response_content_length": len(route_result.content),
        }
    except (InferenceGatewayCallError, TokenFactoryConfigurationError) as error:
        route_receipt = getattr(
            error,
            "receipt",
            {
                "schema": "ProofLaunchResilientInferenceGatewayV1",
                "status": "blocked",
                "reason": type(error).__name__,
                "competition_core_eligible": False,
            },
        )

route_receipt_path.write_text(
    json.dumps(route_receipt, indent=2, sort_keys=True) + "\\n",
    encoding="utf-8",
)
print(json.dumps(route_receipt, indent=2, sort_keys=True))
"""
            ),
            markdown(
                """## 7. Cortex-X V10: exact 1500-item program and truth boundary

This gate does not convert an ambitious TODO list into claimed results. It
loads the canonical 0001–1500 program, verifies all 36 workstreams and their
dependency waves, and keeps every item open until all declared D/A/I/E and
T/P/X evidence locators are hash-bound.

V10 also enforces four non-negotiable boundaries before training:

1. exactly one Supervisor owns authoritative state;
2. simulated/proxy business outcomes are displayed only as predicted;
3. every breakthrough must pass technical, product, and effect gates; and
4. a failed bet may close with negative evidence but cannot enter production.
"""
            ),
            code(
                """from prooflaunch_remix.quality_contract import QualityTier, contract_for
from prooflaunch_remix.v10_program import CortexProgram
from prooflaunch_remix.v10_training import default_v10_training_plan

program_path = repo / "docs" / "CORTEX_X_V10_1500_TODO.md"
program = CortexProgram.from_files((program_path,))
assert len(program.todos) == 1500
assert program.todos[0].todo_id == "0001"
assert program.todos[-1].todo_id == "1500"
assert len(program.ordered_workstreams()) == 36

v10_contract = contract_for(QualityTier.CORTEX_X_V10)
assert len(v10_contract.metrics) == 28
assert not v10_contract.evaluate({
    "schema": "ProofLaunchCortexXV10CompiledEvidenceV1",
    "four_a_overall_mean": 5.0,
}).passed, "partial aggregate must fail closed"

training_plan = default_v10_training_plan()
assert len(training_plan.stages) == 6
assert training_plan.radeon_required
assert training_plan.multi_gpu_required
assert training_plan.minimum_world_size >= 2
assert training_plan.preferred_world_size >= 4
assert training_plan.preferred_strategy == "ddp"
assert training_plan.memory_fallback_strategy == "fsdp2"
assert training_plan.single_gpu_baseline_required
assert not training_plan.single_gpu_may_promote
assert training_plan.maximum_resident_heavy_models_per_rank == 1
assert training_plan.judge_human_label_minimum >= 100
print(json.dumps({
    "todo_count": len(program.todos),
    "workstream_count": len(program.ordered_workstreams()),
    "quality_bar_count": len(v10_contract.metrics),
    "training_stage_count": len(training_plan.stages),
    "program_summary": program.summary,
}, indent=2))
"""
            ),
            markdown(
                """## 8. Frontier-20-lens teacher-corpus gate

All 1,500 tasks must pass the nine-stage source-bound development pipeline
before the corpus is admitted to implementation planning:

`Architect + Research → Critic → Implementer → Verifier + 4A Critic → Synthesis → Frontier Judge → Final Repair`.

The validator blocks truncated output, placeholders, inferred licenses,
score-gate gaming, missing prerequisites, secret patterns, incomplete strict
JSON, or any teacher attempt to mark a TODO complete. These records remain
private external teacher advisory; they do not count as local Radeon evidence
and do not enter model weights until the separate provider-output rights gate
is explicitly unblocked. Raw episodes are intentionally excluded from the
public submission archive; mount or generate the private corpus only inside an
authorized environment.
"""
            ),
            code(
                """import subprocess
import sys

teacher_corpus = repo / "data" / "tokenfactory_teacher_v10"
teacher_receipt = (
    repo / "evidence" / "v10" / "tokenfactory-corpus-validation.json"
)
if not teacher_corpus.is_dir():
    raise FileNotFoundError(
        "Frontier teacher corpus is absent; all nine stages remain blocked"
    )
subprocess.run(
    [
        sys.executable,
        str(repo / "scripts" / "validate_tokenfactory_corpus.py"),
        "--corpus-root",
        str(teacher_corpus),
        "--output",
        str(teacher_receipt),
    ],
    check=True,
)
teacher_validation = json.loads(
    teacher_receipt.read_text(encoding="utf-8")
)
assert teacher_validation["status"] == "passed"
assert teacher_validation["quality_protocol"] == "frontier-20-lens-v3"
assert all(
    count == 750
    for count in teacher_validation["stage_valid_counts"].values()
)
assert teacher_validation["competition_core_eligible"] is False
teacher_rights = json.loads(
    (
        repo / "evidence" / "v10" / "tokenfactory-output-rights.json"
    ).read_text(encoding="utf-8")
)
assert teacher_rights["status"] == "rights_review_required"
assert teacher_rights["training_eligible"] is False
assert teacher_rights["redistribution_eligible"] is False
print(json.dumps(teacher_validation, indent=2, sort_keys=True))
"""
            ),
            markdown(
                """## 8A. Top-10 agency campaign-distillation gate

The frozen 2026 North-American cohort must contain all ten ranked reference
agencies, at least one fully source-bound 16-layer case for each, and zero raw
campaign assets or sealed-evaluation overlap. The separate 300-case admission
gate remains blocked until every agency has 30 distinct cases.

All 1,500 TODOs also receive strategy, craft, effectiveness, and synthesis
passes. The final synthesis is strict JSON, references only the frozen case
IDs, carries a common Top-10 context digest, and stays in the
`research_reference` partition.
"""
            ),
            code(
                """four_a_manifest = json.loads(
    (
        repo / "config" / "north_america_4a_research_cohort_2026.json"
    ).read_text(encoding="utf-8")
)
assert len(four_a_manifest["agencies"]) == 10
required_layers = set(four_a_manifest["distillation_layers"])
fully_distilled_agencies = {
    case["agency_id"]
    for case in four_a_manifest["seed_cases"]
    if set(case["layers"]) == required_layers
}
assert fully_distilled_agencies == {
    agency["agency_id"] for agency in four_a_manifest["agencies"]
}
assert four_a_manifest["admission"]["raw_campaign_assets_stored"] is False
assert four_a_manifest["admission"]["training"] is False

four_a_receipt = (
    repo / "evidence" / "v10" / "four-a-transfer-corpus-validation.json"
)
subprocess.run(
    [
        sys.executable,
        str(repo / "scripts" / "validate_four_a_transfer_corpus.py"),
        "--corpus-root",
        str(teacher_corpus),
        "--output",
        str(four_a_receipt),
    ],
    check=True,
)
four_a_validation = json.loads(
    four_a_receipt.read_text(encoding="utf-8")
)
assert four_a_validation["status"] == "passed"
assert four_a_validation["complete"] is True
assert all(
    count == 750
    for count in four_a_validation["valid_counts"].values()
)
assert four_a_validation["four_a_context_sha256"]
assert four_a_validation["competition_core_eligible"] is False
print(json.dumps(four_a_validation, indent=2, sort_keys=True))
"""
            ),
            markdown(
                """## 8B. Official-floor plus overdelivery gate

The phrase “200% quality” is not treated as an invented numeric score. It is
implemented as two non-substitutable gates for every canonical TODO:

1. every applicable official requirement; and
2. an overdelivery profile covering source, positive/negative tests, stop and
   rollback, plus applicable research, training, multimodal, 4K, Radeon,
   blind-4A, and human evidence.

Teacher prose, API spend, self-scores, simulations, and local proxies cannot
satisfy external evidence facets.
"""
            ),
            code(
                """double_standard_path = (
    repo / "evidence" / "v10" / "double-standard-requirements.json"
)
if not double_standard_path.exists():
    raise FileNotFoundError(
        "V10 double-standard requirements are absent; run "
        "scripts/build_v10_excellence_requirements.py"
    )
double_standard = json.loads(
    double_standard_path.read_text(encoding="utf-8")
)
assert double_standard["schema"] == (
    "ProofLaunchV10DoubleStandardRequirementsV1"
)
assert double_standard["todo_count"] == 1500
assert len(double_standard["requirements"]) == 1500
assert [
    item["todo_id"] for item in double_standard["requirements"]
] == [f"{index:04d}" for index in range(1, 1501)]
assert all(
    item["official_floor"] and item["overdelivery_gate"]
    for item in double_standard["requirements"]
)
assert double_standard["coverage"] == {
    "todos_with_applicable_official_floor": 1500,
    "todos_with_direct_submission_floor": 100,
    "todos_with_overdelivery_gate": 1500,
    "todos_with_required_facets": 1500,
    "todos_with_multigpu_program_binding": 1500,
    "todos_requiring_direct_multigpu_observation": 1100,
    "proxy_external_evidence_allowed": False,
}
print(json.dumps({
    "todo_count": double_standard["todo_count"],
    "requirements_sha256": double_standard["requirements_sha256"],
    "coverage": double_standard["coverage"],
}, indent=2))

multigpu_plan_path = (
    repo / "evidence" / "v10" / "multigpu-execution-plan.json"
)
if not multigpu_plan_path.exists():
    raise FileNotFoundError(
        "V10 multi-GPU plan is absent; run "
        "scripts/build_v10_multigpu_plan.py"
    )
multigpu_plan = json.loads(
    multigpu_plan_path.read_text(encoding="utf-8")
)
assert multigpu_plan["schema"] == (
    "ProofLaunchV10MultiGpuExecutionPlanV1"
)
assert multigpu_plan["coverage"]["todo_count"] == 1500
assert (
    multigpu_plan["coverage"]["todos_with_program_multigpu_binding"]
    == 1500
)
assert (
    multigpu_plan["coverage"][
        "todos_requiring_direct_multigpu_observation"
    ]
    == 1100
)
assert (
    multigpu_plan["strategy_policy"]["forbidden_training_strategy"]
    == "device_map=auto"
)
assert all(
    item["current_status"] == "not_started"
    for item in multigpu_plan["plans"]
)
multigpu_contract_for_hash = dict(multigpu_plan)
multigpu_expected_contract_hash = multigpu_contract_for_hash.pop(
    "contract_sha256"
)
assert hashlib.sha256(
    json.dumps(
        multigpu_contract_for_hash,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest() == multigpu_expected_contract_hash
print(json.dumps({
    "todo_plan_sha256": multigpu_plan["todo_plan_sha256"],
    "contract_sha256": multigpu_plan["contract_sha256"],
    "coverage": multigpu_plan["coverage"],
}, indent=2))
"""
            ),
            markdown(
                """## 9. Multi-GPU Radeon curriculum execution gate

The curriculum is strictly sequential:

`multimodal CPT → curriculum SFT → direct feedback → on-policy distillation → multi-objective RL → sparse adapter consolidation`.

Inside each stage, DDP is the default after per-rank memory-fit preflight;
FSDP2 is allowed only as the verified memory fallback. World size, global
batch, immutable revisions, rank shards, and checkpoint ownership are frozen.
The one-GPU run is required only as an equivalence baseline and may not
promote a multi-GPU claim.

The vision/audio towers and base weights remain frozen. Each stage records
every-rank receipts, checkpoints atomically, runs general multimodal retention
plus stage-specific gates, and rolls back on failure. Training cannot start
from an ad-hoc dataset: the corpus manifest must prove content-hash
decontamination, temporal holdout, source locator, and
owned/permissive/public-domain rights for every sample.
"""
            ),
            code(
                """from prooflaunch_remix.v10_training import (
    DataRight,
    DataSplit,
    TrainingCorpusManifest,
    TrainingSample,
)

corpus_path = repo / "evidence" / "v10" / "training" / "corpus-manifest.json"
if not corpus_path.exists():
    raise FileNotFoundError(
        "V10 training is blocked: create the rights-audited, decontaminated "
        f"corpus manifest at {corpus_path}"
    )

corpus_payload = json.loads(corpus_path.read_text(encoding="utf-8"))
corpus = TrainingCorpusManifest(
    samples=tuple(
        TrainingSample(
            **{
                **row,
                "source_right": DataRight(row["source_right"]),
                "split": DataSplit(row["split"]),
            }
        )
        for row in corpus_payload["samples"]
    ),
    temporal_holdout_start=corpus_payload["temporal_holdout_start"],
)
corpus_audit = corpus.audit()
print(json.dumps(corpus_audit.__dict__, indent=2, default=str))
assert corpus_audit.passed, corpus_audit.failures
assert preflight_report["passed"], "Radeon preflight must pass before training"

multigpu_preflight_path = (
    repo / "evidence" / "RADEON_MULTIGPU_PREFLIGHT_2026-07-30.json"
)
multigpu_preflight = json.loads(
    multigpu_preflight_path.read_text(encoding="utf-8")
)
assert multigpu_preflight["status"] == "passed", (
    "Direct training is blocked until a >=2-GPU Radeon/RCCL preflight passes"
)
assert (
    multigpu_preflight["observed"]["torchCudaDeviceCount"]
    >= training_plan.minimum_world_size
)
"""
            ),
            markdown(
                """## 10. V10 measured-result compiler

No metric is prefilled. The final cell accepts only a compiled result with raw
human comparison counts, five frozen baselines, real Radeon coverage, all
twelve breakthrough bundles, at least three promoted bets, and the 28 V10
quality bars. Absence of those files is a truthful blocked state.
"""
            ),
            code(
                """v10_evidence_path = (
    repo / "evidence" / "v10" / "cortex-x-v10-compiled-evidence.json"
)
v10_report_path = repo / "evidence" / "v10" / "cortex-x-v10-quality-report.json"

if not v10_evidence_path.exists():
    raise FileNotFoundError(
        "V10 certification is blocked: measured compiled evidence is absent"
    )
v10_evidence = json.loads(v10_evidence_path.read_text(encoding="utf-8"))
v10_report = v10_contract.evaluate(v10_evidence)
v10_report_path.parent.mkdir(parents=True, exist_ok=True)
v10_report_path.write_text(
    json.dumps(v10_report.to_dict(), indent=2, sort_keys=True) + "\\n",
    encoding="utf-8",
)
print(json.dumps(v10_report.to_dict(), indent=2, sort_keys=True))
assert v10_report.passed, "one or more Cortex-X V10 bars failed"
"""
            ),
        ]
    )
    metadata = notebook.setdefault("metadata", {}).setdefault("prooflaunch", {})
    metadata.update(
        {
            "schema": "ProofLaunchCortexXV10RadeonGate",
            "version": "1.0.0",
            "todoCount": 1500,
            "workstreamCount": 36,
            "breakthroughBetCount": 12,
            "requiredPromotedBreakthroughs": 3,
            "qualityTier": "cortex_x_v10",
            "qualityMetricCount": 28,
            "trainingStageCount": 6,
            "trainingPlanSchema": "ProofLaunchTrainingPlanMultiGpuV10",
            "teacherCorpusQualityProtocol": "frontier-20-lens-v3",
            "teacherCorpusStageCount": 9,
            "fourATransferStageCount": 4,
            "fourAReferenceAgencyCount": 10,
            "fourAFullyDistilledCaseCount": 13,
            "doubleStandardRequirementCount": 1500,
            "officialFloorAndOverdeliveryRequired": True,
            "proxyExternalEvidenceAllowed": False,
            "multiGpuPlanTodoCount": 1500,
            "multiGpuProgramBindingCount": 1500,
            "directMultiGpuObservationTodoCount": 1100,
            "multiGpuRequiredForCompute": True,
            "allowedSilentSingleGpuFallback": False,
            "multiGpuTrainingStrategyOrder": ["ddp", "fsdp2"],
            "teacherOutputRightsStatus": "rights_review_required",
            "teacherOutputTrainingEligible": False,
            "trainingStageOrder": [
                "multimodal_cpt",
                "curriculum_sft",
                "direct_feedback",
                "on_policy_distillation",
                "multi_objective_rl",
                "adapter_expert_consolidation",
            ],
            "judgeHumanLabelMinimum": 100,
            "judgeTprMinimum": 0.8,
            "judgeTnrMinimum": 0.8,
            "singleSupervisorStateOwner": True,
            "simulatedBusinessOutcomesPredictedOnly": True,
            "minimumTrainingWorldSize": 2,
            "preferredTrainingWorldSize": 4,
            "singleRadeonBaselineRequired": True,
            "singleRadeonMayPromote": False,
            "maxResidentHeavyModelsPerRank": 1,
            "archiveName": "prooflaunch-radeon-v10.tar.gz",
            "archivePartsGlob": "prooflaunch-radeon-v10.part-*",
            "archiveChecksumName": "prooflaunch-radeon-v10.sha256",
            "realRadeonExecutionRequired": True,
            "prefilledV10MetricsAllowed": False,
            "externalInferencePriority": [
                "amd_radeon_token_factory",
                "approved_fireworks_fallback",
            ],
            "tokenFactoryEndpoint": (
                "https://developer.amd.com.cn/radeon/api/v1/chat/completions"
            ),
            "externalInferenceCompetitionCoreEligible": False,
            "externalInferenceSecretPersistenceAllowed": False,
        }
    )
    DESTINATION.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(DESTINATION)


if __name__ == "__main__":
    main()
