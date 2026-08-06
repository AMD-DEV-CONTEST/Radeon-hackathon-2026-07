#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_contracts import stable_digest
from prooflaunch_remix.v10_reuse_governance import (
    BuildObservation,
    CandidateAssessment,
    HealthObservation,
    IntegrationMode,
    ReuseDecision,
    ReuseManifest,
    ReuseReview,
    RocmEvidenceLevel,
    UpstreamCategory,
    UpstreamProject,
    duplicate_function_fingerprints,
    find_unmediated_imports,
    select_build_strategy,
    smoke_plan,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/cortex_x_v10_reuse_manifest_v1.json"
EVIDENCE = ROOT / "evidence/v10/reuse-manifest-v1-mechanical-fixture.json"
OBSERVED_AT = "2026-07-31T22:55:00Z"


def project(
    project_id: str,
    name: str,
    repository: str,
    revision: str,
    pushed_at: str,
    categories: tuple[UpstreamCategory, ...],
    license_spdx: str,
    license_path: str,
    mode: IntegrationMode,
    import_roots: tuple[str, ...],
    hardware: str,
    cuda_only: tuple[str, ...] = (),
    rocm_candidates: tuple[str, ...] = (),
    *,
    license_approved: bool = True,
) -> UpstreamProject:
    repository_url = f"https://github.com/{repository}"
    license_url = (
        repository_url
        if license_path == "UNRESOLVED"
        else f"{repository_url}/blob/{revision}/{license_path}"
    )
    return UpstreamProject(
        project_id=project_id,
        name=name,
        repository_url=repository_url,
        revision=revision,
        observed_at=OBSERVED_AT,
        pushed_at=pushed_at,
        categories=categories,
        license_spdx=license_spdx,
        license_evidence_url=license_url,
        license_approved_for_code_reuse=license_approved,
        integration_mode=mode,
        import_roots=import_roots,
        hardware_assumption=hardware,
        cuda_only_components=cuda_only,
        rocm_candidate_components=rocm_candidates,
        rocm_evidence_level=RocmEvidenceLevel.UNTESTED,
    )


def projects() -> tuple[UpstreamProject, ...]:
    C = UpstreamCategory
    A = IntegrationMode.ADAPTER
    W = IntegrationMode.WRAPPER
    F = IntegrationMode.WORKFLOW
    R = IntegrationMode.REFERENCE_ONLY
    return (
        project("flux2", "FLUX.2", "black-forest-labs/flux2", "50fe5162777813d869182b139e83b10743caef15", "2026-03-12T15:06:20Z", (C.MODEL, C.IMAGE), "Apache-2.0", "LICENSE.md", A, ("flux2",), "Reference path is CUDA-first; weights and model license are separate from source code.", ("CUDA attention and model kernels",), ("Python orchestration",)),
        project("wan2.2", "Wan2.2", "Wan-Video/Wan2.2", "42bf4cfaa384bc21833865abc2f9e6c0e67233dc", "2026-03-17T10:48:41Z", (C.MODEL, C.VIDEO), "Apache-2.0", "LICENSE.txt", W, ("wan",), "Reference inference is NVIDIA/CUDA-first and high-memory.", ("flash attention and distributed inference",), ("PyTorch graph outside custom kernels",)),
        project("ltx-video", "LTX-Video", "Lightricks/LTX-Video", "4b2d053057623ddd4d0a1d3e9cd28890e9ef487f", "2026-01-05T22:37:07Z", (C.MODEL, C.VIDEO), "Apache-2.0", "LICENSE", W, ("ltx_video",), "Reference path documents CUDA GPUs; ROCm kernel parity is unverified.", ("attention acceleration",), ("scheduler and workflow code",)),
        project("seedvr2", "SeedVR2", "IceClear/SeedVR2", "dc248c05946b64114012ac9a0da8faf982159627", "2026-01-27T06:18:41Z", (C.MODEL, C.VIDEO, C.SUPER_RESOLUTION), "Apache-2.0", "LICENSE", W, ("seedvr2",), "Reference restoration path is CUDA-first.", ("CUDA inference optimizations",), ("tiling and workflow planning",)),
        project("real-esrgan", "Real-ESRGAN", "xinntao/Real-ESRGAN", "a4abfb2979a7bbff3f69f58f58ae324608821e27", "2024-08-06T13:15:18Z", (C.IMAGE, C.SUPER_RESOLUTION), "BSD-3-Clause", "LICENSE", A, ("realesrgan",), "PyTorch reference supports CPU/CUDA; ROCm has not been observed here.", ("optional CUDA extensions",), ("RRDB tensor graph",)),
        project("swinir", "SwinIR", "JingyunLiang/SwinIR", "6545850fbf8df298df73d81f3e8cba638787c8bd", "2024-05-14T07:05:48Z", (C.IMAGE, C.SUPER_RESOLUTION), "Apache-2.0", "LICENSE", A, ("models",), "PyTorch reference uses CUDA examples; pure tensor path is a ROCm candidate.", (), ("SwinIR inference graph",)),
        project("grounding-dino", "Grounding DINO", "IDEA-Research/GroundingDINO", "856dde20aee659246248e20734ef9ba5214f5e44", "2024-08-12T08:52:02Z", (C.MODEL, C.IMAGE), "Apache-2.0", "LICENSE", A, ("groundingdino",), "Reference build includes compiled operators and CUDA assumptions.", ("custom deformable attention operators",), ("tokenization and box post-processing",)),
        project("sam2", "SAM 2.1", "facebookresearch/sam2", "2b90b9f5ceec907a1c18123530e92e794ad901a4", "2026-05-30T02:29:40Z", (C.MODEL, C.IMAGE, C.VIDEO, C.SEGMENTATION), "Apache-2.0", "LICENSE", A, ("sam2",), "Reference path is PyTorch CUDA-first with optional compiled extension.", ("connected-components extension and CUDA acceleration",), ("Python predictor orchestration",)),
        project("siglip2", "SigLIP 2", "google-research/big_vision", "0127fb6b337ee2a27bf4e54dea79cff176527356", "2025-05-19T13:55:52Z", (C.MODEL, C.IMAGE, C.EVALUATION), "Apache-2.0", "LICENSE", A, ("big_vision",), "Official research code is JAX and TPU/GPU oriented; Transformers inference is separately pinned.", ("JAX accelerator assumptions",), ()),
        project("clap", "LAION CLAP", "LAION-AI/CLAP", "1fd4c37df5ffbfcfbad5415c170bc66cf94c9994", "2025-05-15T19:55:29Z", (C.MODEL, C.AUDIO, C.EVALUATION), "CC0-1.0", "LICENSE", A, ("laion_clap",), "PyTorch CPU/CUDA reference; ROCm inference is untested.", (), ("audio preprocessing and PyTorch encoder graph",)),
        project("ms-swift", "ms-swift", "modelscope/ms-swift", "a5229fda7ebcc141e7a0d6bd12030c043ce26486", "2026-07-31T09:46:17Z", (C.TRAINING, C.MODEL), "Apache-2.0", "LICENSE", A, ("swift",), "Training framework spans CUDA/NPU paths; exact ROCm recipe must be smoke-tested.", ("backend-specific fused kernels",), ("dataset and trainer orchestration",)),
        project("transformers", "Transformers", "huggingface/transformers", "3717b9cda226af7377da1944f395af0eac6e2b51", "2026-07-31T20:19:04Z", (C.MODEL, C.TRAINING), "Apache-2.0", "LICENSE", A, ("transformers",), "Python framework delegates device support to PyTorch and model kernels.", (), ("tokenizers, processors and generic PyTorch models",)),
        project("peft", "PEFT", "huggingface/peft", "ea8ebf36da98d93fdfca020ad17ab746e6994c01", "2026-07-31T12:22:16Z", (C.TRAINING, C.MODEL), "Apache-2.0", "LICENSE", A, ("peft",), "Python adapter framework delegates accelerator support to PyTorch.", (), ("LoRA injection and adapter lifecycle",)),
        project("trl", "TRL", "huggingface/trl", "aa592026c7267a52a60ce751a28e90bc303531fe", "2026-07-31T22:45:25Z", (C.TRAINING, C.EVALUATION), "Apache-2.0", "LICENSE", A, ("trl",), "Trainer orchestration is portable; vLLM and fused optimizer paths may be CUDA-specific.", ("optional vLLM and fused training backends",), ("SFT and preference trainer control plane",)),
        project("langgraph", "LangGraph", "langchain-ai/langgraph", "b2926a0ff9589c28c7e01fe7cdbb337b86d5a4b4", "2026-07-31T17:54:40Z", (C.AGENT, C.MARKETING_AGENT), "MIT", "LICENSE", F, ("langgraph",), "CPU control plane; inference hardware is determined by connected model adapters.", (), ("state graph, checkpoint and human-gate control plane",)),
        project("agent-r1", "Agent-R1", "AgentR1/Agent-R1", "b124aa46534cbf2fb8bc8af11405774984c42ac7", "2026-07-27T18:00:21Z", (C.TRAINING, C.AGENT), "MIT", "LICENSE", R, ("agent_r1",), "verl/vLLM reference training is multi-GPU CUDA-first.", ("verl and vLLM rollout/training stack",), ("Step-level MDP schemas",)),
        project("matpo", "MATPO", "mzf666/MATPO", "3c41d62d96963ac0512573f9d2e51596720ab379", "2025-10-31T10:16:36Z", (C.TRAINING, C.AGENT), "Apache-2.0", "LICENSE", R, ("verl",), "Research implementation assumes CUDA distributed training and external model APIs in data setup.", ("distributed rollout and training",), ("role/task schema ideas",)),
        project("marti", "MARTI", "TsinghuaC3I/MARTI", "a2fe2c7b9ec46cf24769c90575c51d847f41d04e", "2026-04-14T03:28:29Z", (C.TRAINING, C.AGENT), "MIT", "LICENSE", R, ("openrlhf",), "Reference minimum is approximately 8x80GB CUDA GPUs per agent.", ("OpenRLHF/vLLM distributed training",), ("centralized reward and workflow schemas",)),
        project("opsd", "OPSD", "siyan-zhao/OPSD", "7448751f307a9cdbcc1246dd1565a1a605b443df", "2026-05-10T05:46:29Z", (C.TRAINING,), "UNRESOLVED", "UNRESOLVED", R, ("opsd",), "Research code is CUDA-first; repository source license was not resolved.", ("distributed teacher/student training",), (), license_approved=False),
        project("tcod", "TCOD", "kokolerk/TCOD", "465eef4406ad0cff675b36bd46f37f28b1736ff9", "2026-07-09T07:25:54Z", (C.TRAINING, C.AGENT), "Apache-2.0", "LICENSE", R, ("verl",), "Reference temporal curriculum uses CUDA distributed training.", ("verl/vLLM training",), ("trajectory scheduling logic",)),
        project("rcm", "rCM", "NVlabs/rcm", "ed3cb14dd936f92cdc9f9381af7369991509b41f", "2026-06-25T16:45:05Z", (C.TRAINING, C.VIDEO), "Apache-2.0", "LICENSE.txt", R, ("rcm",), "NVIDIA research implementation is CUDA-first.", ("diffusion training and fused attention",), ()),
        project("causal-forcing", "Causal Forcing", "thu-ml/Causal-Forcing", "1fc7bbc19a503c1bce80ecef08158b20e702f386", "2026-07-23T05:51:04Z", (C.TRAINING, C.VIDEO), "Apache-2.0", "LICENSE", R, ("causal_forcing",), "Research training and inference are CUDA-first.", ("video diffusion kernels",), ("workflow-level causality controls",)),
        project("paddleocr", "PaddleOCR", "PaddlePaddle/PaddleOCR", "2661c7c0ef5c613e8f93c6e93b2e052399f0f854", "2026-07-22T11:59:34Z", (C.MODEL, C.OCR, C.EVALUATION), "Apache-2.0", "LICENSE", A, ("paddleocr",), "Paddle CPU/CUDA reference; ROCm backend is not observed.", ("Paddle CUDA inference",), ("OCR evaluation schemas",)),
        project("evalscope", "EvalScope", "modelscope/evalscope", "e66e415b6871b760139b9d81fb047a007c21daca", "2026-07-31T06:07:56Z", (C.EVALUATION,), "Apache-2.0", "LICENSE", A, ("evalscope",), "Evaluation control plane is CPU-portable; evaluated model backends vary.", (), ("dataset, metric and report orchestration",)),
        project("whisper", "Whisper", "openai/whisper", "5f86d1d86363843179951550570367b37c5d6f78", "2026-07-28T20:18:29Z", (C.MODEL, C.AUDIO), "MIT", "LICENSE", A, ("whisper",), "PyTorch CPU/CUDA reference; ROCm inference has not been observed here.", (), ("audio preprocessing and PyTorch model graph",)),
        project("crewai", "CrewAI", "crewAIInc/crewAI", "c8f441cffa1c9412003a1f535ba464a39b4de60d", "2026-07-31T16:55:55Z", (C.AGENT, C.MARKETING_AGENT), "MIT", "LICENSE", F, ("crewai",), "CPU orchestration; model execution is delegated to configured providers.", (), ("role/workflow control plane",)),
        project("autogen", "AutoGen", "microsoft/autogen", "027ecf0a379bcc1d09956d46d12d44a3ad9cee14", "2026-04-15T11:59:09Z", (C.AGENT, C.MARKETING_AGENT), "CC-BY-4.0", "LICENSE-CODE", R, ("autogen",), "CPU orchestration; code-license suitability requires separate legal review.", (), ("conversation and tool workflow concepts",), license_approved=False),
        project("openai-agents", "OpenAI Agents SDK", "openai/openai-agents-python", "ff0e7866f1b8e8b88fd6d8f49bce0068ca92027f", "2026-07-31T22:39:23Z", (C.AGENT, C.MARKETING_AGENT), "MIT", "LICENSE", F, ("agents",), "CPU orchestration; model inference is provider-dependent and not competition-core eligible online.", (), ("handoff, guardrail and tracing control plane",)),
    )


REQUIRED_PINS = (
    "flux2", "wan2.2", "ltx-video", "seedvr2", "real-esrgan", "swinir",
    "grounding-dino", "sam2", "siglip2", "clap", "ms-swift", "peft", "trl",
    "langgraph", "agent-r1", "matpo", "marti", "opsd", "tcod", "rcm",
    "causal-forcing",
)


def main() -> int:
    roster = projects()
    normalized_snapshot = [
        {
            "project_id": item.project_id,
            "repository_url": item.repository_url,
            "revision": item.revision,
            "pushed_at": item.pushed_at,
            "license_spdx": item.license_spdx,
            "license_evidence_url": item.license_evidence_url,
        }
        for item in roster
    ]
    manifest = ReuseManifest(
        projects=roster,
        required_pins=REQUIRED_PINS,
        observed_at=OBSERVED_AT,
        source_snapshot_sha256=stable_digest(normalized_snapshot),
    )
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(CONFIG, json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    environment = "e" * 64
    build_rows = (
        BuildObservation("wheel", environment, True, 8.0, 320.0, "a" * 64),
        BuildObservation("source_build", environment, True, 85.0, 1400.0, "b" * 64),
    )
    duplicate_fixture = """
def first(value):
    return value + 1

def second(value):
    return value + 1
"""
    review = ReuseReview(
        module_path="src/prooflaunch_remix/v10_reuse_governance.py",
        need="content-addressed cross-upstream reuse governance and fail-closed ROCm admission",
        candidates=(
            CandidateAssessment("langgraph", next(item.revision for item in roster if item.project_id == "langgraph"), True, False, "workflow runtime does not provide source-license, revision, ROCm and patch governance"),
            CandidateAssessment("crewai", next(item.revision for item in roster if item.project_id == "crewai"), True, False, "agent orchestration does not provide a cross-repository reuse manifest"),
        ),
        decision=ReuseDecision.BUILD,
        selected_project_id=None,
        falsifiable_benefit="reject every unpinned, unlicensed or unobserved-ROCm execution candidate in deterministic tests",
        evidence_locator="tests/test_v10_reuse_governance.py",
    )
    health = {
        item.project_id: HealthObservation(
            item.project_id,
            item.archived,
            item.pushed_at,
            OBSERVED_AT,
            item.license_approved_for_code_reuse,
            True,
            False,
        ).score()
        for item in roster
    }
    receipt = {
        "schema": "ProofLaunchReuseManifestMechanicalFixtureV1",
        "manifest_sha256": sha256_file(CONFIG),
        "manifest_content_sha256": manifest.to_dict()["content_sha256"],
        "project_count": len(roster),
        "required_pin_count": len(REQUIRED_PINS),
        "category_count": len(UpstreamCategory),
        "license_blocked_project_ids": [item.project_id for item in roster if not item.license_approved_for_code_reuse],
        "rocm_observed_project_count": sum(item.rocm_evidence_level is RocmEvidenceLevel.OBSERVED for item in roster),
        "executable_admitted_project_count": sum(item.executable_admission for item in roster),
        "smoke_plan": smoke_plan(manifest),
        "patch_registry": {"patch_count": 0, "status": "ready_empty", "manifest": "upstream_patches/manifest.json"},
        "wheel_vs_build_fixture": {
            "evidence_class": "simulated_contract_fixture",
            "selected": select_build_strategy(build_rows),
            "rows": [row.__dict__ for row in build_rows],
        },
        "direct_import_fixture": {
            "source": "from diffusers import DiffusionPipeline",
            "findings": find_unmediated_imports("from diffusers import DiffusionPipeline", ("diffusers",)),
        },
        "duplicate_scan_fixture": {
            "evidence_class": "simulated_contract_fixture",
            "groups": duplicate_function_fingerprints(duplicate_fixture),
        },
        "health_scores_without_runtime_smoke": health,
        "self_reuse_review": {
            "module_path": review.module_path,
            "decision": review.decision.value,
            "candidate_count": len(review.candidates),
            "falsifiable_benefit": review.falsifiable_benefit,
        },
        "live_upstream_smokes": 0,
        "live_rocm_smokes": 0,
        "patches_applied": 0,
        "truth_boundary": (
            "This receipt proves catalog and governance mechanics on normalized official metadata and synthetic contract fixtures. "
            "It does not prove any upstream runs on Radeon, model-weight/data rights, upstream benchmark quality, build speed, "
            "or an applied patch. Every upstream therefore remains non-executable-admitted."
        ),
    }
    receipt["content_sha256"] = stable_digest(receipt)
    atomic_write_text(EVIDENCE, json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"projects": len(roster), "pins": len(REQUIRED_PINS), "manifest_sha256": sha256_file(CONFIG), "evidence_sha256": sha256_file(EVIDENCE)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
