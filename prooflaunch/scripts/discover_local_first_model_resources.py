#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "config/cortex_x_v10_frontier_api_panel.json"
OUTPUT = ROOT / "evidence/v10/local-first-model-resource-discovery.json"
OLLAMA_MANIFESTS = Path.home() / ".ollama/models/manifests/registry.ollama.ai/library"
HF_HUB = Path.home() / ".cache/huggingface/hub"
SWIFT = Path("/usr/bin/swift")
VISION_FRAMEWORK = Path("/System/Library/Frameworks/Vision.framework")


def discover_ollama() -> list[str]:
    if not OLLAMA_MANIFESTS.exists():
        return []
    models: list[str] = []
    for manifest in sorted(path for path in OLLAMA_MANIFESTS.rglob("*") if path.is_file()):
        relative = manifest.relative_to(OLLAMA_MANIFESTS)
        if len(relative.parts) >= 2:
            models.append(f"{'/'.join(relative.parts[:-1])}:{relative.parts[-1]}")
    return models


def discover_huggingface(hub: Path = HF_HUB) -> list[str]:
    if not hub.exists():
        return []
    return sorted(
        path.name.removeprefix("models--").replace("--", "/")
        for path in hub.glob("models--*")
        if path.is_dir()
        and (path / "snapshots").is_dir()
        and any(candidate.is_file() for candidate in (path / "snapshots").rglob("*"))
    )


def discover_native_capabilities(
    *, swift: Path = SWIFT, vision_framework: Path = VISION_FRAMEWORK
) -> dict[str, str | None]:
    return {
        "document_ocr": (
            "apple-vision/VNRecognizeTextRequest"
            if swift.is_file() and vision_framework.is_dir()
            else None
        )
    }


def select_local_roles(
    ollama: list[str],
    huggingface: list[str],
    native_capabilities: dict[str, str | None] | None = None,
) -> dict[str, object]:
    available = set(ollama) | set(huggingface)

    def choose(*ordered: str) -> str | None:
        return next((model for model in ordered if model in available), None)

    return {
        "semantic_memory_and_retrieval": choose("bge-m3:latest"),
        "structured_text_baseline": choose(
            "mlx-community/gemma-3-12b-it-4bit",
            "qwen2.5-coder:1.5b",
        ),
        "image_generation": choose(
            "AbstractFramework/flux.2-klein-9b-8bit",
            "AbstractFramework/qwen-image-2512-8bit",
        ),
        "image_editing": choose("AbstractFramework/qwen-image-edit-2511-8bit"),
        "video_generation": choose(
            "dgrauet/ltx-2.3-mlx",
            "AbstractFramework/wan2.2-t2v-a14b-diffusers-bf16",
        ),
        "image_to_video": choose("AbstractFramework/wan2.2-i2v-a14b-diffusers-bf16"),
        "video_restoration": choose("ByteDance-Seed/SeedVR2-7B"),
        "speech_and_voice_design": choose(
            "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16",
            "mlx-community/Ming-omni-tts-0.5B-4bit",
        ),
        "audio_generation": choose("mlx-community/LongCat-AudioDiT-1B-bf16"),
        "document_ocr": choose("PaddlePaddle/PP-OCRv6_medium_rec")
        or (native_capabilities or {}).get("document_ocr"),
    }


def main() -> int:
    panel = json.loads(PANEL.read_text(encoding="utf-8"))
    ollama = discover_ollama()
    huggingface = discover_huggingface()
    native_capabilities = discover_native_capabilities()
    local_roles = select_local_roles(ollama, huggingface, native_capabilities)
    candidates = panel["candidates"]
    credential_names = sorted({str(row["api_key_env"]) for row in candidates})
    credential_state = {name: bool(os.environ.get(name, "").strip()) for name in credential_names}
    executable_cloud = [
        str(row["candidate_id"])
        for row in candidates
        if credential_state[str(row["api_key_env"])]
    ]
    report = {
        "schema": "ProofLaunchLocalFirstModelResourceDiscoveryV1",
        "observed_at": date.today().isoformat(),
        "panel_sha256": sha256_file(PANEL),
        "download_performed": False,
        "secret_persisted": False,
        "local_first": True,
        "ollama_models": ollama,
        "huggingface_cached_models": huggingface,
        "native_capabilities": native_capabilities,
        "local_role_assignment": local_roles,
        "local_role_coverage": {
            "covered": sum(model is not None for model in local_roles.values()),
            "possible": len(local_roles),
            "missing": [role for role, model in local_roles.items() if model is None],
        },
        "cloud_api_candidate_count": len(candidates),
        "zero_cost_api_candidate_count": sum(
            row["access_class"] == "zero_cost_rate_limited" for row in candidates
        ),
        "developer_credit_api_candidate_count": sum(
            row["access_class"] == "developer_credits" for row in candidates
        ),
        "free_compute_route_count": len(panel["free_compute_matrix"]),
        "credential_environment_present": credential_state,
        "executable_cloud_candidate_ids": executable_cloud,
        "execution_policy": [
            "reuse an observed local model before any model download",
            "use free APIs only for public or synthetic teacher, challenger and judge work",
            "do not admit API output into training until model-specific output rights pass review",
            "use free GPU only for checkpointed offline training or evaluation",
            "export checkpoints, metrics, environment lock and hashes before instance shutdown",
            "retain Radeon-local key inference as a separate competition proof gate",
        ],
        "status": (
            "local_ready_cloud_ready"
            if executable_cloud
            else "local_ready_cloud_blocked_missing_credentials"
        ),
    }
    if report["local_role_coverage"]["covered"] < 8:
        raise RuntimeError("local cache no longer covers the minimum multimodal role set")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "local_roles": report["local_role_coverage"],
                "executable_cloud_candidates": len(executable_cloud),
                "download_performed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
