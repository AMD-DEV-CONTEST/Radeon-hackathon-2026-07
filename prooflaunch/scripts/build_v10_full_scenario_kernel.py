#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_agentomnia import (
    ApplicationSplit,
    AtomicDifficulty,
    Capability,
    DatasetPartition,
    ReasoningRoute,
)
from prooflaunch_remix.v10_contracts import stable_digest
from prooflaunch_remix.v10_frontier_landscape import default_frontier_landscape
from prooflaunch_remix.v10_frontier_training_kernel import (
    default_frontier_training_kernel,
)


ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def main() -> int:
    landscape = default_frontier_landscape()
    frontier_kernel = default_frontier_training_kernel()
    kernel = {
        "schema": "ProofLaunchFullScenarioGTMKernelV10",
        "as_of": "2026-07-31",
        "research_basis": [
            {
                "title": "AgentOmnia: Scaling Agentic Models for Full-Scenario Applications",
                "url": "https://arxiv.org/abs/2607.23124",
                "use": "method reference; no claim that its private corpus/code/model is present",
            },
            {
                "title": "OmniaBench: Benchmarking General AI Agents Across Diverse Scenarios",
                "url": "https://arxiv.org/abs/2607.14989",
                "use": "public evaluation taxonomy and benchmark reference",
            },
            {
                "title": "OmniaBench public evaluation repository",
                "url": "https://github.com/scuuy/OmniaBench",
                "use": "Apache-2.0 evaluation code; dataset license checked separately",
            },
            *[
                {
                    "title": item.title,
                    "url": item.url,
                    "use": item.evidence_boundary,
                }
                for item in frontier_kernel.mechanisms
                if item.url
                not in {
                    "https://arxiv.org/abs/2607.23124",
                    "https://arxiv.org/abs/2607.14989",
                }
            ],
        ],
        "coordinate_system": {
            "application_splits": [item.value for item in ApplicationSplit],
            "capabilities": [item.value for item in Capability],
            "atomic_difficulties": [item.value for item in AtomicDifficulty],
            "reasoning_routes": [item.value for item in ReasoningRoute],
            "partitions": [item.value for item in DatasetPartition],
            "task_rule": "every environment, task, trajectory, verifier, reward and failure shares one coordinate",
        },
        "training_kernel": {
            "environment_gate": [
                "code-driven and stateful",
                "immutable revision",
                "explicit license",
                "healthcheck passed",
                "resettable",
                "golden trajectory replay verified",
            ],
            "sft": [
                "format validation",
                "verifier-confirmed visible action/observation trajectories",
                "capability-aware convergence budgeting",
                "strict train/evaluation environment-revision isolation",
            ],
            "online_rl": [
                "rule plus calibrated rubric rewards",
                "discard environment failures",
                "all-fail-only verified partial gold-prefix recovery",
                "student suffix remains on-policy",
                "freeze checkpoint, seed and curriculum each round",
                "training/inference token and route consistency receipt",
            ],
            "failure_diagnosis": [
                "first error",
                "propagation",
                "missed detection",
                "repair",
                "stop",
                "reward-hacking versus judge/environment/policy attribution",
            ],
            "prd_evolution": [
                "failure-cell PRD",
                "new environment and task proposals",
                "health and contamination gate",
                "target benchmark diagnosis",
                "external held-out transfer",
                "multi-round regression control",
            ],
        },
        "frontier_product_landscape": landscape.to_dict(),
        "frontier_training_kernel": frontier_kernel.to_dict(),
        "promotion_gates": {
            "single_common_policy": "no benchmark-specific adapter",
            "corpus": "owned/permissive/public-domain/expressly-licensed only",
            "reward_model": "advanced rubric, rank, advantage direction, magnitude and repeatability all pass",
            "multimodal": "video/audio/text/data artifacts have lane-specific objective plus blind-human gates",
            "gtm": "strategy-to-activation-to-measurement lifecycle succeeds without manual hidden repair",
            "radeon": "at least one key inference observed on AMD Radeon",
            "distributed": "real >=2 GPU DDP/FSDP2 receipt; single GPU cannot promote",
            "truth": "no simulated metric is promoted as trained-weight or business evidence",
        },
        "content_sha256": None,
    }
    kernel["content_sha256"] = stable_digest(
        {key: value for key, value in kernel.items() if key != "content_sha256"}
    )
    config_path = ROOT / "config/cortex_x_v10_full_scenario_gtm_kernel.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(config_path, json.dumps(kernel, ensure_ascii=False, indent=2) + "\n")

    closure = _read_json(ROOT / "evidence/v10/todo-closure-report.json")
    radeon = _read_json(ROOT / "evidence/RADEON_MULTIGPU_PREFLIGHT_2026-07-30.json")
    seed = _read_json(ROOT / "data/v10_gtm_seed/manifest.json")
    trajectory_kd = _read_json(ROOT / "data/v10_trajectory_kd/manifest.json")
    trajectory_runtime = _read_json(
        ROOT / "evidence/v10/trajectory-kd-runtime-audit.json"
    )
    brand_memory = _read_json(ROOT / "data/v10_brand_memory/manifest.json")
    brand_memory_audit = _read_json(
        ROOT / "evidence/v10/brand-memory-seed-audit.json"
    )
    brand_memory_runtime = _read_json(
        ROOT / "evidence/v10/brand-memory-runtime-audit.json"
    )
    memory_card = _read_json(ROOT / "evidence/v10/memory-card.json")
    audit = {
        "schema": "ProofLaunchFullScenarioTrainingAuditV10",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kernel_path": str(config_path.relative_to(ROOT)),
        "kernel_sha256": kernel["content_sha256"],
        "implementation": {
            "coordinate_contract": "implemented_and_locally_testable",
            "step_level_mdp": "implemented_and_locally_testable",
            "failure_attribution": "implemented_and_locally_testable",
            "rcrl_admission": "implemented_and_locally_testable",
            "failure_driven_curriculum": "implemented_and_locally_testable",
            "prd_evolution_gate": "implemented_and_locally_testable",
            "frontier_product_comparison_set": "8_lanes_x_10_non_ranked_references",
            "frontier_research_mechanisms": len(frontier_kernel.mechanisms),
            "full_lifecycle_lane_objectives": len(frontier_kernel.lane_objectives),
            "durable_execution_contract": "checkpointed_idempotent_bounded_and_human_gated",
            "named_eval_failure_modes": len(frontier_kernel.failure_modes),
            "matched_trajectory_distillation_seed": "implemented_and_locally_testable",
            "hierarchical_role_credit": "implemented_and_locally_testable",
            "temporal_trajectory_curriculum": "implemented_and_locally_testable",
            "trajectory_diagnostics_and_ablations": "implemented_on_controlled_mechanical_fixtures",
            "brand_genome_memory_schema": "implemented_and_locally_testable",
            "brand_genome_typed_edges": "implemented_and_locally_testable",
            "brand_genome_policy_supervision": "implemented_as_project_owned_synthetic_seed",
            "brand_genome_hybrid_retrieval": "implemented_on_controlled_fixture_vectors",
            "brand_genome_memory_benchmarks": "implemented_as_memory_only_and_streaming_mechanical_fixtures",
        },
        "observed_training_state": {
            "local_synthetic_executable_environments": seed.get(
                "environment_count", 0
            ),
            "local_synthetic_tasks": seed.get("task_count", 0),
            "verified_visible_trajectories": seed.get("trajectory_count", 0),
            "verified_sft_seed_trajectories": seed.get(
                "partition_counts", {}
            ).get("sft", 0),
            "matched_outcome_trajectories": trajectory_kd.get(
                "outcome_trajectory_count", 0
            ),
            "role_local_trajectories": trajectory_kd.get(
                "role_trajectory_count", 0
            ),
            "visible_policy_distillation_examples": trajectory_kd.get(
                "policy_example_count", 0
            ),
            "step_reward_labels": trajectory_kd.get("step_reward_count", 0),
            "trajectory_reward_labels": trajectory_kd.get(
                "trajectory_reward_count", 0
            ),
            "hierarchical_credit_assignments": trajectory_runtime.get(
                "counts", {}
            ).get("credit_assignments", 0),
            "temporal_curriculum_stage_trajectories": trajectory_runtime.get(
                "counts", {}
            ).get("curriculum_stage_trajectories", {}),
            "controlled_diagnostic_fixtures": trajectory_runtime.get(
                "counts", {}
            ).get("diagnostic_fixtures", 0),
            "brand_memory_atoms": brand_memory.get("atom_count", 0),
            "brand_memory_edges": brand_memory.get("edge_count", 0),
            "brand_memory_policy_examples": brand_memory.get(
                "policy_example_count", 0
            ),
            "brand_memory_event_chain_valid": brand_memory_audit.get(
                "checks", {}
            ).get("event_chain_valid", False),
            "brand_memory_benchmark_cases": brand_memory_runtime.get(
                "metrics", {}
            ).get("case_count", 0),
            "brand_memory_hybrid_retrieval_precision": brand_memory_runtime.get(
                "metrics", {}
            ).get("hybrid_retrieval_precision"),
            "brand_memory_hybrid_stale_recall": brand_memory_runtime.get(
                "metrics", {}
            ).get("hybrid_stale_recall"),
            "brand_memory_hybrid_context_saving": brand_memory_runtime.get(
                "metrics", {}
            ).get("hybrid_mean_context_saving_rate"),
            "brand_memory_mechanical_v1_passed": memory_card.get(
                "mechanical_v1_passed", False
            ),
            "brand_memory_observed_neural_inference": memory_card.get(
                "observed_neural_embedding_inference", False
            ),
            "rl_seed_tasks_not_run": seed.get("partition_counts", {}).get(
                "rl", 0
            ),
            "online_rl_tasks_run": 0,
            "rcrl_rollout_groups_run": 0,
            "prd_evolution_rounds_run": 0,
            "trained_checkpoint_receipts": 0,
            "blind_human_4a_panels": 0,
            "radeon_key_inference_receipts": 0,
            "real_multigpu_training_receipts": 0,
            "currently_observed_gpu_count": radeon.get("observed", {}).get(
                "device_count", 1
            ),
        },
        "todo_state_before_this_audit": {
            "closed": closure.get("closed_count", 0),
            "open": closure.get("open_count", 1500),
        },
        "status": "blocked_from_training_promotion",
        "blockers": [
            "the executable corpus is a 152-task project-owned synthetic mechanical seed, not a scaled 4A multimodal corpus",
            "no real SFT or online RL checkpoint receipt exists",
            "no RCRL rollout was executed against a real policy and resettable environment",
            "no held-out multi-round PRD evolution result exists",
            "no blind North-American-4A-calibrated human preference panel exists",
            "current Radeon template exposes one GPU, below the >=2 GPU promotion requirement",
            "Radeon kernel WebSocket 403 previously prevented a real local key-inference receipt",
        ],
        "next_execution_order": [
            "freeze eight GTM product-lane capability rubrics and falsifiers",
            "land every research mechanism as a source-bound ablation with its declared falsifier",
            "keep L2 as the default and promote bounded L3 phases only after >=90% sealed-eval pass rate",
            "make every state-changing activity checkpointed and idempotent before long-running training",
            "replace metadata-only fixtures with owned/licensed real multimodal bytes",
            "scale healthchecked resettable environments beyond the 32 local seeds",
            "expand tasks across sparse coordinate cells without evaluation leakage",
            "replace mechanical teacher labels with licensed expert and model rollouts",
            "calibrate deterministic step/trajectory rewards against human labels",
            "run single-GPU Radeon equivalence baseline without promotion",
            "run >=2 GPU Radeon SFT with checkpoint-resume receipts",
            "run online RL and inject RCRL prefixes only into clean all-fail groups",
            "diagnose first-error and propagation cells",
            "run at least three sealed PRD-evolution rounds plus external transfer tests",
            "promote only after multimodal, 4A, GTM, safety, cost and Radeon gates all pass",
        ],
        "truth_boundary": (
            "This artifact proves a local training/evaluation contract and gap audit only. "
            "It does not prove trained weights, AgentOmnia reproduction, product superiority, "
            "4A preference, Radeon execution, multi-GPU speedup, or business lift."
        ),
    }
    audit["content_sha256"] = stable_digest(audit)
    audit_path = ROOT / "evidence/v10/full-scenario-training-audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(audit_path, json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "config": str(config_path),
                "audit": str(audit_path),
                "status": audit["status"],
                "product_reference_count": sum(
                    len(item.products) for item in landscape.lanes
                ),
                "kernel_sha256": kernel["content_sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
