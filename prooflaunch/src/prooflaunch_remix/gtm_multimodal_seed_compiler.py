from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .files import atomic_write_text


class MultimodalSeedCompilationError(ValueError):
    pass


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _seed(admission_sha: str, stage: str, lane: int = 0) -> int:
    material = f"{admission_sha}:{stage}:{lane}".encode("utf-8")
    return int(hashlib.sha256(material).hexdigest()[:16], 16) & ((1 << 63) - 1)


def _validate_content_addressed(payload: Mapping[str, Any], schema: str) -> None:
    if payload.get("schema") != schema:
        raise MultimodalSeedCompilationError(f"{schema} input is missing")
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned["content_sha256"] = None
    if not isinstance(supplied, str) or not _SHA256.fullmatch(supplied) or supplied != _digest(unsigned):
        raise MultimodalSeedCompilationError(f"{schema} content digest drifted")


def compile_multimodal_seed(
    admission: Mapping[str, Any],
    execution_bindings: Mapping[str, Any],
    gpu_handoff: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile a human-selected text territory into four fail-closed media lanes."""

    _validate_content_addressed(admission, "ProofLaunchMultimodalProductionAdmissionV1")
    if not (
        admission.get("prompt_compilation_authorized") is True
        and admission.get("gpu_execution_authorized") is False
        and admission.get("spend_authorized") is False
        and admission.get("external_publish_authorized") is False
        and admission.get("effect_claim_eligible") is False
    ):
        raise MultimodalSeedCompilationError("multimodal admission escaped its authority boundary")
    if execution_bindings.get("schema") != "ProofLaunchComfyUIExecutionBindingsV1":
        raise MultimodalSeedCompilationError("ComfyUI execution bindings are invalid")
    if gpu_handoff.get("schema") != "ProofLaunchComfyUIGPUHandoffV1":
        raise MultimodalSeedCompilationError("GPU handoff is invalid")
    workflows = execution_bindings.get("workflows")
    if not isinstance(workflows, Mapping):
        raise MultimodalSeedCompilationError("ComfyUI workflow bindings are missing")
    required_workflows = {
        "qwen-image-2512",
        "ltx-2.3-text-to-video",
        "wan2.2-text-to-video",
        "ace-step-1.5-text-to-audio",
    }
    if not required_workflows <= set(workflows):
        raise MultimodalSeedCompilationError("required multimodal workflow bindings are incomplete")
    selected = admission.get("selected_candidate")
    if not isinstance(selected, Mapping):
        raise MultimodalSeedCompilationError("selected candidate is missing")
    candidate_sha = selected.get("candidate_content_sha256")
    unsigned_candidate = dict(selected)
    unsigned_candidate.pop("candidate_content_sha256", None)
    if candidate_sha != _digest(unsigned_candidate):
        raise MultimodalSeedCompilationError("selected candidate digest drifted")
    channels = selected.get("channels")
    if not isinstance(channels, list) or len(channels) != 2:
        raise MultimodalSeedCompilationError("selected candidate channels are incomplete")
    proof = selected.get("factual_claims")
    if not isinstance(proof, list) or len(proof) != 1 or not isinstance(proof[0], str):
        raise MultimodalSeedCompilationError("selected candidate proof is invalid")
    admission_sha = str(admission["content_sha256"])
    idea = str(selected.get("organizing_idea") or "").strip()
    tension = str(selected.get("cultural_tension") or "").strip()
    mechanism = str(selected.get("participation_mechanism") or "").strip()
    if not all((idea, tension, mechanism)):
        raise MultimodalSeedCompilationError("selected creative territory is incomplete")
    first = channels[0]
    if not isinstance(first, Mapping) or not isinstance(first.get("body"), list):
        raise MultimodalSeedCompilationError("selected primary channel is invalid")
    spoken_lines = [str(first.get("hook") or ""), *map(str, first["body"]), str(first.get("cta") or "")]
    spoken_script = "\n".join(line for line in spoken_lines if line.strip())
    image_prompt = (
        f"Campaign organizing idea: {idea}. Cultural tension: {tension}. "
        f"Participation mechanism: {mechanism}. Approved proof to communicate through the scene: {proof[0]}. "
        "Create one premium editorial campaign key visual with a decisive focal hierarchy, "
        "credible material detail, restrained brand-safe composition, generous copy-safe negative "
        "space, no logos, no legible text, no unsupported product feature, and no stock-photo cliché."
    )
    video_prompt = (
        f"Five-second campaign film built around: {idea}. Begin with the tension ({tension}), "
        f"transform through the participation mechanism ({mechanism}), and resolve on visual evidence "
        f"consistent with: {proof[0]}. Cinematic live-action realism, coherent subject identity, "
        "controlled camera movement, edit-safe beginning and ending, no text, no logos, no added claim."
    )
    music_tags = (
        "instrumental campaign score, modern editorial pulse, human warmth, restrained confidence, "
        "clean transient structure, no imitation of a named artist, no copyrighted melody"
    )
    selected_handoff = set(gpu_handoff.get("selected_workflow_ids") or [])
    stages = [
        {
            "stage_id": "hero_image",
            "modality": "image",
            "workflow_id": "qwen-image-2512",
            "workflow_selected_in_gpu_handoff": "qwen-image-2512" in selected_handoff,
            "values": {"prompt": image_prompt, "width": 1328, "height": 1328, "seed": _seed(admission_sha, "hero_image")},
            "execution_admitted": False,
            "blockers": ["target GPU preflight", "local weight SHA-256 verification", "real artifact receipt"],
        },
        {
            "stage_id": "hero_video",
            "modality": "video",
            "workflow_id": None,
            "workflow_candidates": ["ltx-2.3-text-to-video", "wan2.2-text-to-video"],
            "values": {"prompt": video_prompt, "seconds": 5, "fps": 25, "seed": _seed(admission_sha, "hero_video")},
            "execution_admitted": False,
            "blockers": ["video component and model rights gate", "target GPU preflight", "real artifact receipt"],
        },
        {
            "stage_id": "original_music",
            "modality": "audio",
            "workflow_id": "ace-step-1.5-text-to-audio",
            "workflow_selected_in_gpu_handoff": "ace-step-1.5-text-to-audio" in selected_handoff,
            "values": {"tags": music_tags, "lyrics": "[Instrumental]", "duration_seconds": 30.0, "bpm": 112, "language": "en", "planner_seed": _seed(admission_sha, "music", 0), "sampler_seed": _seed(admission_sha, "music", 1)},
            "execution_admitted": False,
            "blockers": ["target GPU preflight", "local weight SHA-256 verification", "real artifact receipt", "music rights review"],
        },
        {
            "stage_id": "speech",
            "modality": "speech",
            "workflow_id": None,
            "values": {"script": spoken_script, "language": "en", "voice_identity": "unassigned_rights_cleared_voice"},
            "execution_admitted": False,
            "blockers": ["rights-cleared voice selection", "speech workflow admission", "human pronunciation review"],
        },
    ]
    receipt: dict[str, Any] = {
        "schema": "ProofLaunchMultimodalSeedCompilationV1",
        "multimodal_admission_sha256": admission_sha,
        "selected_territory_id": admission["selected_territory_id"],
        "selected_candidate_content_sha256": candidate_sha,
        "gpu_handoff_plan_sha256": gpu_handoff.get("plan_sha256"),
        "stage_count": len(stages),
        "stages": stages,
        "status": "compiled_all_execution_blocked",
        "all_required_modalities_compiled": True,
        "all_required_modalities_executable": False,
        "automatic_external_action_enabled": False,
        "master_mux_authorized": False,
        "human_craft_review_completed": False,
        "external_publish_executed": False,
        "effect_claim_eligible": False,
        "truth_boundary": (
            "This deterministic bridge compiles a complete human-selected territory into image, "
            "video, original-music and speech requests. It does not execute a model, create media, "
            "clear unresolved rights, authorize GPU use or publish, or prove preference, lift, "
            "revenue, 4A quality or Top-1 standing."
        ),
        "content_sha256": None,
    }
    receipt["content_sha256"] = _digest(receipt)
    return receipt


def compile_multimodal_seed_files(
    admission_path: str | Path,
    execution_bindings_path: str | Path,
    gpu_handoff_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    sources = [Path(path).expanduser().resolve(strict=True) for path in (admission_path, execution_bindings_path, gpu_handoff_path)]
    if any(path.is_symlink() or not path.is_file() for path in sources):
        raise MultimodalSeedCompilationError("compiler inputs must be real files")
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sources]
    receipt = compile_multimodal_seed(*payloads)
    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise MultimodalSeedCompilationError("refusing to overwrite an existing compilation receipt")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write_text(target, json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    target.chmod(0o600)
    return receipt


__all__ = [
    "MultimodalSeedCompilationError",
    "compile_multimodal_seed",
    "compile_multimodal_seed_files",
]
