#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_research_ledger import (
    EvidenceStrength,
    FalsifiableStudy,
    MetricDirection,
    MetricGate,
    ResearchDisposition,
    ResearchSource,
    StudyBudget,
    innovation_combinations,
    negative_experiments,
    research_queue,
    result_leaderboard,
    validate_registry,
)
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/cortex_x_v10_research_ledger_v1.json"
EVIDENCE = ROOT / "evidence/v10/research-ledger-v1-mechanical-fixture.json"
NEGATIVE_MANIFEST = ROOT / "research/negative_experiments/manifest.json"


def source(
    research_id: str,
    todo_id: str,
    topic: str,
    title: str,
    primary_url: str,
    version_date: str,
    code_url: str | None,
    revision: str | None,
    hardware: str,
    scope: str,
    failures: tuple[str, ...],
    mechanism: str,
    transfer: str,
) -> ResearchSource:
    return ResearchSource(
        research_id=research_id,
        todo_id=todo_id,
        topic=topic,
        title=title,
        primary_url=primary_url,
        version_date=version_date,
        official_implementation_url=code_url,
        implementation_revision=revision,
        implementation_status=(
            "official_revision_frozen" if code_url else "no_official_code_verified"
        ),
        hardware_scale=hardware,
        original_task_scope=scope,
        known_failure_modes=failures,
        mechanism=mechanism,
        local_transfer=transfer,
        evidence_strength=(
            EvidenceStrength.CODE_INSPECTED if code_url else EvidenceStrength.PAPER_INSPECTED
        ),
    )


def sources() -> tuple[ResearchSource, ...]:
    multimodal_paper = "https://arxiv.org/abs/2603.03276"
    multimodal_hardware = (
        "Controlled from-scratch IsoFLOP multimodal pretraining; the exact accelerator count "
        "is not asserted by this registry because it was not resolved from primary metadata."
    )
    return (
        source("R0107", "0107", "unified-multimodal-pretraining", "Beyond Language Modeling: An Exploration of Multimodal Pretraining", multimodal_paper, "2026-03-03", None, None, multimodal_hardware, "Joint text, image, video, image-text and action-conditioned-video pretraining under controlled from-scratch comparisons.", ("vision is materially more data-hungry than language", "a shared objective can improve generation while regressing understanding"), "Next-token language and diffusion vision losses share a Transfusion substrate.", "Use a staged owned-data curriculum and a frozen retention gate; do not reproduce foundation-scale pretraining."),
        source("R0108", "0108", "rae-unified-visual-representation", "Beyond Language Modeling: Representation Autoencoder comparison", multimodal_paper, "2026-03-03", None, None, multimodal_hardware, "Controlled comparison of visual tokenizers for both understanding and generation.", ("paper-scale RAE compute exceeds the single-card budget", "representation gains may not transfer to Gemma-family towers"), "A representation autoencoder is evaluated as one visual latent space for recognition and synthesis.", "Ablate frozen processor embeddings versus a small owned projection adapter; never replace the image tower without retention evidence."),
        source("R0109", "0109", "multimodal-data-collaboration", "Beyond Language Modeling: visual-language data synergy", multimodal_paper, "2026-03-03", None, None, multimodal_hardware, "IsoFLOP mixtures of text, video, paired image-text and action-conditioned video.", ("mixture imbalance can starve a modality", "synergy on pretraining losses may not improve GTM artifacts"), "Language and visual data provide complementary gradients rather than independent curricula.", "Use provenance-cleared interleaves and compare joint versus isolated curricula at equal tokens and wall time."),
        source("R0110", "0110", "world-model-emergence", "Beyond Language Modeling: world-model emergence", multimodal_paper, "2026-03-03", None, None, multimodal_hardware, "Action-conditioned video prediction inside unified multimodal pretraining.", ("visual prediction is not proof of actionable planning", "pixel plausibility can hide causal or identity errors"), "World-model behavior emerges from general multimodal prediction including actions.", "Keep the Campaign World Model symbolic and bounded until action-conditioned prediction beats a no-world-model control."),
        source("R0111", "0111", "modality-specialized-moe", "Beyond Language Modeling: modality-specialized Mixture-of-Experts", multimodal_paper, "2026-03-03", None, None, multimodal_hardware, "IsoFLOP MoE scaling across language and vision data regimes.", ("router collapse", "single-card expert residency can erase sparse-compute gains"), "MoE capacity naturally specializes by modality and helps reconcile asymmetric data scaling.", "Route small role adapters with a permanent generalist fallback; reject any route that breaches VRAM or retention gates."),
        source("R0112", "0112", "tracer1", "Anticipatory Planning for Multimodal AI Agents", "https://arxiv.org/abs/2603.16777", "2026-03-17", None, None, "Seven online/offline computer-use and multimodal tool-use benchmarks; exact accelerator count not verified.", "Two-stage RL for multimodal computer-use and tool-use agents.", ("forecasting may add latency without executability gains", "frozen tool feedback may not cover changing GTM environments"), "Trajectory-level forecasting precedes grounded execution refinement.", "Add bounded future-state forecasts to the planner and compare against reactive and one-stage controls."),
        source("R0113", "0113", "agent-r1", "Agent-R1: A Unified and Modular Framework for Agentic Reinforcement Learning", "https://arxiv.org/abs/2511.14460", "2026-05-30", "https://github.com/AgentR1/Agent-R1", "b124aa46534cbf2fb8bc8af11405774984c42ac7", "Multi-GPU CUDA-first verl/vLLM reference; report evaluates Qwen3-4B.", "Step-native multi-turn agent RL across tool and environment tasks.", ("environment drift can invalidate rollouts", "NaN and context-growth failures are documented in repository history"), "Every turn is an explicit MDP transition with observation, action, feedback and reward.", "Directly adopt the typed step schema and replay boundary, not the reported learned scores."),
        source("R0114", "0114", "m3-agent", "M3: High-fidelity Text-to-Image Generation via Multi-Modal, Multi-Agent and Multi-Round Visual Reasoning", "https://arxiv.org/abs/2602.06166", "2026-02-05", None, None, "Training-free orchestration over off-the-shelf image and multimodal models; runtime depends on selected APIs/weights.", "Complex compositional text-to-image generation on OneIG-EN and GenEval.", ("iterative edits can regress already-satisfied constraints", "multiple closed APIs make cost and reproducibility variable"), "Planner, Checker, Refiner, Editor and Verifier repair one compositional constraint at a time.", "Use an invariant checklist and monotonic verifier around the existing image compiler."),
        source("R0115", "0115", "ns-mem", "Advancing Multimodal Agent Reasoning with Long-Term Neuro-Symbolic Memory", "https://arxiv.org/abs/2603.15280", "2026-03-16", None, None, "Multimodal reasoning benchmark experiments; exact accelerator count not verified.", "Long-term episodic, semantic and rule memory for multimodal agents.", ("symbol extraction can introduce false rules", "rule and embedding stores can disagree"), "Neural similarity retrieval is combined with explicit symbolic rules and deterministic queries.", "Adopt typed episodic/semantic/rule partitions with source-bound rule provenance and conflict tests."),
        source("R0116", "0116", "taskmem", "Task-Focused Memorization for Multimodal Agents", "https://arxiv.org/abs/2605.31075", "2026-05-29", None, None, "Qwen3-VL-30B-A3B two-phase policy learning on streaming VideoMME, EgoLife and EgoTempo variants.", "Learning what to retain from unbounded multimodal streams for future tasks.", ("task reward can erase broadly useful memory", "raw-video leakage invalidates memory-only evaluation"), "A deployment-time adapter optimizes a task-conditioned memorization policy.", "Use memory-only and streaming tests now; defer the learned adapter until a rights-cleared Radeon run exists."),
        source("R0117", "0117", "sage", "SAGE: A Self-Evolving Agentic Graph-Memory Engine", "https://arxiv.org/abs/2605.12061", "2026-05-12", None, None, "Graph-memory retrieval across QA and long-term memory benchmarks; exact accelerator count not verified.", "Writer-reader feedback for evolving structure-aware graph memory.", ("feedback can reinforce graph errors", "Graph Foundation Model cost may dominate retrieval"), "A graph reader supplies structural feedback to an incremental memory writer.", "Adopt typed evolving edges and writer/reader separation; keep the current deterministic reader as control."),
        source("R0118", "0118", "matpo", "MATPO: Multi-Agent Tool-Integrated Policy Optimization", "https://arxiv.org/abs/2510.04678", "2025-10-08", "https://github.com/mzf666/MATPO", "3c41d62d96963ac0512573f9d2e51596720ab379", "Qwen3-4B example uses 8x80GB A800; full reported setup lists 128 training plus 16 inference A100/A800 80GB GPUs.", "Planner/worker roles inside one LLM for web-search and multi-hop QA agents.", ("LoRA path is explicitly not thoroughly evaluated", "central rewards can hide role-specific failure"), "One policy plays planner and worker roles with role-aware credit.", "Reuse role/task schemas and compare a single-base role adapter against separate agents."),
        source("R0119", "0119", "marti", "MARTI: Multi-Agent Reinforced Training and Inference", "https://openreview.net/forum?id=E7jZqo0A50", "2026-01-25", "https://github.com/TsinghuaC3I/MARTI", "a2fe2c7b9ec46cf24769c90575c51d847f41d04e", "Minimum 8x80GB GPUs per agent; MARTI-v2 reports 3 nodes of 8 H200 GPUs.", "Centralized multi-agent interaction/reward with distributed policy training; v2 adds code tree search.", ("hardware scale is infeasible in the current single-Radeon window", "central reward may misassign cross-agent credit"), "Central interaction and rewarding coordinate separately trained agent policies.", "Adopt workflow/reward schemas only; keep full MARTI training in the infeasible register."),
        source("R0120", "0120", "test-time-scaling", "LLMs Improving LLMs: Agentic Discovery for Test-Time Scaling", "https://arxiv.org/abs/2605.08083", "2026-05-08", "https://github.com/zhengkid/AutoTTS", "3cd98d12c7cb999afc5c21381f22ea5811ac6c05", "Controller discovery reported $39.9 and 160 minutes over pre-collected trajectories; serving hardware is model-dependent.", "Width/depth controller synthesis for mathematical-reasoning trajectories.", ("more inference can reduce cost efficiency", "controller search can overfit probe signals"), "A controller learns when to branch, continue, probe, prune and stop.", "Use a hard-capped GTM branch controller and select only Pareto improvements over direct and fixed-depth plans."),
        source("R0121", "0121", "vipo", "ViPO: Visual Preference Optimization at Scale", "https://arxiv.org/abs/2604.24953", "2026-04-27", None, None, "1M 1024px image pairs and 300K 720p+ video pairs; training accelerator count not verified.", "Image/video preference optimization across diverse visual-generation models.", ("public preference pairs may not be licensed for this project", "conflicting dimensions make pairwise labels noisy"), "Poly-DPO adapts confidence to preference-data noise; high-quality balanced data can make standard DPO sufficient.", "Reuse multidimensional preference schemas and noise diagnostics on owned/synthetic assets only."),
        source("R0122", "0122", "opsd", "On-Policy Self-Distillation for Large Language Models", "https://arxiv.org/abs/2601.18734", "2026-03-18", "https://github.com/siyan-zhao/OPSD", "7448751f307a9cdbcc1246dd1565a1a605b443df", "Updated Qwen3-1.7B recipe reports about 15 minutes on 4xH100.", "Token-level self-distillation on student rollouts with privileged teacher context.", ("privileged context can suppress correction branches", "repository license remains unresolved for code reuse"), "One model acts as student and privileged-context teacher on on-policy tokens.", "Run only as a bounded ablation with fork-rate and correction-retention metrics; do not copy unresolved-license code."),
        source("R0123", "0123", "opsd-failure", "Rethinking On-Policy Self-Distillation for Thinking Models", "https://arxiv.org/abs/2607.05184", "2026-07-06", None, None, "Five Qwen3/OLMo thinking models on AIME24, AIME25 and HMMT25; exact accelerator count not verified.", "Failure analysis of privileged OPSD on long reasoning traces.", ("short-task gains can conceal long-horizon regression", "privileged teachers penalize verification and backtracking tokens"), "High-entropy fork diagnostics explain why privileged context can reverse OPSD gains.", "Make fork, hedging, verification, recovery and long-rollout avg@k mandatory kill gates."),
        source("R0124", "0124", "opd-dynamics", "Rethinking the Dynamics and Mechanism of On-Policy Distillation", "https://arxiv.org/abs/2604.13016", "2026-04-15", "https://github.com/thunlp/OPD", "4532fd35ccfdde82adc918b265e4c964534e83d1", "All reported experiments used 8xNVIDIA A800 80GB GPUs.", "OPD success/failure across LLM reasoning with token-overlap diagnostics.", ("teacher and student thinking styles may be incompatible", "a stronger teacher may add no novel information"), "Support overlap and teacher novelty predict whether OPD succeeds.", "Pre-screen teacher/student overlap and information gain before any distillation spend."),
        source("R0125", "0125", "sdft", "Self-Distillation Enables Continual Learning", "https://arxiv.org/abs/2601.19897", "2026-01-27", None, None, "Sequential skill and knowledge experiments; exact accelerator count not verified.", "Continual learning from demonstrations with a demonstration-conditioned self-teacher.", ("outdated facts are hard to update", "in-context teacher quality bounds the student"), "On-policy demonstration-conditioned self-distillation reduces forgetting versus ordinary SFT.", "Compare against SFT at equal examples and preserve a sealed prior-capability regression set."),
        source("R0126", "0126", "tcod", "TCOD: Exploring Temporal Curriculum in On-Policy Distillation for Multi-turn Autonomous Agents", "https://arxiv.org/abs/2604.24005", "2026-04-29", "https://github.com/kokolerk/TCOD", "465eef4406ad0cff675b36bd46f37f28b1736ff9", "CUDA-first Trinity-RFT/vLLM training on ALFWorld, WebShop and ScienceWorld.", "Temporal curriculum for long multi-turn agent distillation.", ("curriculum direction is environment-dependent", "long trajectories can still move off teacher support"), "Forward-to-backward and backward-to-forward curricula progressively expand trajectory depth.", "Directly adopt bounded short-to-long scheduling logic and compare both directions against flat OPD."),
        source("R0127", "0127", "caopd", "The Illusion of Certainty: Decoupling Capability and Calibration in On-Policy Distillation", "https://arxiv.org/abs/2604.16830", "2026-04-21", "https://github.com/SalesforceAIResearch/CaOPD", "46624a0111d5697df0089ec66c1da249ce59f84c", "Single node of 8xH200 for default 7B-8B settings.", "Calibration-aware OPD on science QA and tool use.", ("empirical confidence needs enough verified rollouts", "task accuracy can improve while calibration degrades"), "Student rollout success replaces privileged teacher self-confidence.", "Use empirical task success and Brier/ECE gates for all teacher-generated confidence claims."),
        source("R0128", "0128", "sdpo", "Reinforcement Learning via Self-Distillation", "https://arxiv.org/abs/2601.20802", "2026-01-28", "https://github.com/lasgroup/SDPO", "7c457fc1b1f636ae794eb0362ba37d4743b06fbc", "Multi-GPU on-policy rollout/logit training; exact paper accelerator count not asserted by this registry.", "Dense token-level learning from rich environment feedback in code and reasoning.", ("late-stage collapse and response drift are reported", "feedback leakage can reward formatting artifacts"), "A feedback-conditioned self-teacher turns rich verifier text into token-level supervision.", "Ablate against GRPO with drift, OOD, formatting and long-horizon stability gates."),
        source("R0129", "0129", "rcm", "rCM: Score-Regularized Continuous-Time Consistency Model", "https://arxiv.org/abs/2510.08431", "2026-06-25", "https://github.com/NVlabs/rcm", "ed3cb14dd936f92cdc9f9381af7369991509b41f", "CUDA-first Wan 1.3B/14B distillation with multi-GPU context parallelism.", "Few-step video diffusion distillation and causal/autoregressive extension.", ("joint sCM and DMD training can be unstable", "quality/diversity trade-off changes with sigma"), "Score regularization stabilizes continuous-time consistency training; staged dCM-to-sCM-to-DMD is recommended.", "Reuse evaluation and staged-training concepts; full training remains outside the single-card budget."),
        source("R0130", "0130", "causal-forcing", "Causal Forcing: Autoregressive Diffusion Distillation Done Right", "https://arxiv.org/abs/2602.02214", "2026-02-02", "https://github.com/thu-ml/Causal-Forcing", "1fc7bbc19a503c1bce80ecef08158b20e702f386", "CUDA-first autoregressive video training over Wan-style checkpoints and curated latent data.", "Few-step real-time interactive autoregressive video generation.", ("base model is limited to roughly five seconds/81 frames", "long-video comparisons are invalid without a matched extension"), "Causal ODE or consistency initialization bridges teacher forcing and self forcing.", "Adopt causal evaluation and matched-horizon comparison; do not claim long-video or Radeon parity."),
        source("R0131", "0131", "seedvr2", "SeedVR2: One-Step Video Restoration via Diffusion Adversarial Post-Training", "https://arxiv.org/abs/2506.05301", "2026-01-27", "https://github.com/IceClear/SeedVR2", "dc248c05946b64114012ac9a0da8faf982159627", "High-resolution CUDA-first one-step restoration; memory depends on tiled output resolution.", "One-step real-world high-resolution video restoration.", ("restoration can hallucinate brand details", "full-resolution memory can exceed a single GPU"), "Adaptive window attention plus feature-matching adversarial post-training restores arbitrary resolutions in one step.", "Directly reuse tiled workflow and identity/claim retention checks around the released restorer."),
    )


DIRECT = {"R0113", "R0114", "R0115", "R0120", "R0124", "R0126", "R0127", "R0131"}
SIMPLIFY = {"R0107", "R0108", "R0109", "R0110", "R0111", "R0112", "R0116", "R0117", "R0121"}
ABLATE = {"R0118", "R0122", "R0123", "R0125", "R0128"}
INFEASIBLE = {"R0119", "R0129", "R0130"}


def disposition(research_id: str) -> ResearchDisposition:
    if research_id in DIRECT:
        return ResearchDisposition.DIRECT_ADOPT
    if research_id in SIMPLIFY:
        return ResearchDisposition.EQUIVALENT_SIMPLIFICATION
    if research_id in ABLATE:
        return ResearchDisposition.ABLATION_ONLY
    if research_id in INFEASIBLE:
        return ResearchDisposition.INFEASIBLE_CURRENT_BUDGET
    raise RuntimeError(f"unclassified research id: {research_id}")


def studies(registry: tuple[ResearchSource, ...]) -> tuple[FalsifiableStudy, ...]:
    rows = []
    for item in registry:
        mode = disposition(item.research_id)
        single_card = 5 if mode is ResearchDisposition.DIRECT_ADOPT else 4 if mode is ResearchDisposition.EQUIVALENT_SIMPLIFICATION else 2 if mode is ResearchDisposition.ABLATION_ONLY else 0
        transferability = 5 if mode in {ResearchDisposition.DIRECT_ADOPT, ResearchDisposition.EQUIVALENT_SIMPLIFICATION} else 3 if mode is ResearchDisposition.ABLATION_ONLY else 1
        commercial = 5 if item.research_id in {"R0112", "R0113", "R0114", "R0116", "R0120", "R0121", "R0126", "R0127", "R0131"} else 4
        rows.append(
            FalsifiableStudy(
                research_id=item.research_id,
                hypothesis=(
                    f"At equal public/synthetic examples and wall-time, {item.local_transfer} "
                    "will improve frozen GTM task success without exceeding the regression or cost gate."
                ),
                controls=(
                    "current V10 path with the candidate mechanism disabled",
                    "equal-budget simplest mature upstream baseline",
                ),
                metrics=(
                    MetricGate("frozen_gtm_task_success_rate", MetricDirection.MIN, 0.80),
                    MetricGate("sealed_regression_rate", MetricDirection.MAX, 0.005),
                    MetricGate("evidence_complete_rate", MetricDirection.MIN, 1.0),
                    MetricGate("budget_overrun_rate", MetricDirection.MAX, 0.0),
                ),
                budget=StudyBudget(
                    gpu_minutes=30 if single_card >= 4 else 15,
                    wall_minutes=60,
                    external_api_usd=0.0,
                    maximum_examples=64,
                ),
                stop_condition=(
                    f"Stop at the first hard-gate breach or if this documented failure appears: {item.known_failure_modes[0]}."
                ),
                disposition=mode,
                transferability_score=transferability,
                single_card_score=single_card,
                commercial_value_score=commercial,
            )
        )
    return tuple(rows)


def enum_json(value: object) -> object:
    if isinstance(value, (EvidenceStrength, ResearchDisposition, MetricDirection)):
        return value.value
    raise TypeError(type(value).__name__)


def main() -> int:
    registry = sources()
    experiments = studies(registry)
    validate_registry(registry, experiments)
    queue = research_queue(experiments)
    receipts = ()
    leaderboard = result_leaderboard(experiments, receipts)
    negatives = negative_experiments(receipts)
    combinations = innovation_combinations(experiments, receipts)
    payload = {
        "schema": "ProofLaunchResearchLedgerV1",
        "frozen_at": "2026-07-31",
        "policy": {
            "primary_or_official_sources_only": True,
            "citation_is_not_reproduction": True,
            "paper_reported_scores_are_never_observed_scores": True,
            "subjective_example_only_experiments_forbidden": True,
            "negative_results_are_retained": True,
            "Radeon_observation_requires_a_hardware_receipt": True,
        },
        "counts": {
            "research_sources": len(registry),
            "falsifiable_studies": len(experiments),
            "executed_receipts": len(receipts),
            "result_leaderboard": len(leaderboard),
            "negative_experiments": len(negatives),
            "promoted_combinations": len(combinations),
        },
        "sources": [asdict(item) for item in registry],
        "studies": [asdict(item) for item in experiments],
        "disposition_lists": {
            mode.value: [item.research_id for item in experiments if item.disposition is mode]
            for mode in ResearchDisposition
        },
        "research_queue": [item.research_id for item in queue],
        "result_leaderboard": [],
        "innovation_combination_selector": {
            "maximum_components": 3,
            "selected": list(combinations),
            "status": "no_executed_evidence_no_promotion",
        },
        "truth_boundary": (
            "Research Ledger V1 freezes primary evidence, hypotheses and budgets. It records zero reproduced "
            "or Radeon-observed studies and promotes no research result. Paper scores and mechanical tests are not training evidence."
        ),
    }
    encoded = json.loads(json.dumps(payload, default=enum_json))
    encoded["content_sha256"] = stable_sha256(payload)
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    NEGATIVE_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(CONFIG, json.dumps(encoded, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    negative_payload = {
        "schema": "ProofLaunchNegativeExperimentRepositoryV1",
        "frozen_at": "2026-07-31",
        "entry_count": 0,
        "entries": [],
        "policy": "Any falsified or hard-gate-failed live research receipt is immutable and must be added here.",
        "truth_boundary": "An empty repository means no live research experiment was executed; it is not a claim that no failures exist.",
    }
    atomic_write_text(NEGATIVE_MANIFEST, json.dumps(negative_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    evidence = {
        "schema": "ProofLaunchResearchLedgerMechanicalFixtureV1",
        "ledger_sha256": sha256_file(CONFIG),
        "negative_manifest_sha256": sha256_file(NEGATIVE_MANIFEST),
        "source_count": len(registry),
        "study_count": len(experiments),
        "todo_order": [item.todo_id for item in registry],
        "queue_head": [item.research_id for item in queue[:5]],
        "executed_receipt_count": 0,
        "result_leaderboard_count": 0,
        "negative_experiment_count": 0,
        "promoted_combination_count": 0,
        "truth_boundary": "This fixture proves schema and selector behavior only; no paper or model result was reproduced.",
    }
    atomic_write_text(EVIDENCE, json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"sources": len(registry), "studies": len(experiments), "sha256": sha256_file(CONFIG)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
