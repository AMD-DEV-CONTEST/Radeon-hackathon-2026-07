#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from prooflaunch_remix.files import atomic_write_bytes


OFFICIAL_ROOT = PROJECT_ROOT / "workflows/comfyui-official-20260801"
OUTPUT_ROOT = PROJECT_ROOT / "workflows/comfyui-execution-wrappers-20260801"
CORE_REVISION = "2881e6161081439b1c3fb3b6c1f51b3d272da710"
FRONTEND_VERSION = "1.47.11"


SPECS = {
    "qwen-image-2512": {
        "source": "qwen-image-2512.api.json",
        "source_node_id": "263:251",
        "source_class_type": "VAEDecode",
        "save_node_id": "prooflaunch:save_image",
        "save_class_type": "SaveImage",
        "save_inputs": {
            "images": ["263:251", 0],
            "filename_prefix": "prooflaunch/qwen-image-2512",
        },
        "history_descriptor_key": "images",
    },
    "ltx-2.3-text-to-video": {
        "source": "ltx-2.3-text-to-video.api.json",
        "source_node_id": "324:312",
        "source_class_type": "CreateVideo",
        "save_node_id": "prooflaunch:save_video",
        "save_class_type": "SaveVideo",
        "save_inputs": {
            "video": ["324:312", 0],
            "filename_prefix": "prooflaunch/ltx-2.3",
            "format": "mp4",
            "codec": {"codec": "auto"},
        },
        "history_descriptor_key": "videos",
    },
    "wan2.2-text-to-video": {
        "source": "wan2.2-text-to-video.api.json",
        "source_node_id": "114:117",
        "source_class_type": "CreateVideo",
        "save_node_id": "prooflaunch:save_video",
        "save_class_type": "SaveVideo",
        "save_inputs": {
            "video": ["114:117", 0],
            "filename_prefix": "prooflaunch/wan2.2",
            "format": "mp4",
            "codec": {"codec": "auto"},
        },
        "history_descriptor_key": "videos",
    },
    "ace-step-1.5-text-to-audio": {
        "source": "ace-step-1.5-text-to-audio.api.json",
        "source_node_id": "21:18",
        "source_class_type": "VAEDecodeAudio",
        "save_node_id": "prooflaunch:save_audio",
        "save_class_type": "SaveAudioAdvanced",
        "save_inputs": {
            "audio": ["21:18", 0],
            "filename_prefix": "prooflaunch/ace-step-1.5",
            "format": {"format": "flac"},
        },
        "history_descriptor_key": "audio",
    },
}


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_sha256(payload: object) -> str:
    return sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def main() -> None:
    official_manifest = json.loads(
        (OFFICIAL_ROOT / "manifest.json").read_text(encoding="utf-8")
    )
    official_by_id = {
        workflow["workflow_id"]: workflow for workflow in official_manifest["workflows"]
    }
    if set(official_by_id) != set(SPECS):
        raise SystemExit("wrapper specs must exactly cover the official workflow manifest")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    records = []
    for workflow_id, spec in SPECS.items():
        official = official_by_id[workflow_id]
        source_path = OFFICIAL_ROOT / spec["source"]
        source_bytes = source_path.read_bytes()
        if sha256_bytes(source_bytes) != official["api_sha256"]:
            raise SystemExit(f"official API hash drift: {workflow_id}")
        workflow = json.loads(source_bytes)
        source_node = workflow.get(spec["source_node_id"])
        if not isinstance(source_node, dict) or source_node.get("class_type") != spec[
            "source_class_type"
        ]:
            raise SystemExit(f"terminal media node drift: {workflow_id}")
        if spec["save_node_id"] in workflow:
            raise SystemExit(f"save node already exists in official export: {workflow_id}")
        workflow[spec["save_node_id"]] = {
            "inputs": spec["save_inputs"],
            "class_type": spec["save_class_type"],
            "_meta": {
                "title": "ProofLaunch evidence output wrapper",
                "source_official_api_sha256": official["api_sha256"],
            },
        }
        wrapper_bytes = (
            json.dumps(workflow, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        output_path = OUTPUT_ROOT / f"{workflow_id}.execution-wrapper.json"
        atomic_write_bytes(output_path, wrapper_bytes)
        records.append(
            {
                "workflow_id": workflow_id,
                "official_api_path": str(source_path.relative_to(PROJECT_ROOT)),
                "official_api_sha256": official["api_sha256"],
                "wrapper_path": str(output_path.relative_to(PROJECT_ROOT)),
                "wrapper_sha256": sha256_bytes(wrapper_bytes),
                "official_node_count": len(workflow) - 1,
                "wrapper_node_count": len(workflow),
                "terminal_media_node_id": spec["source_node_id"],
                "terminal_media_class_type": spec["source_class_type"],
                "output_node_id": spec["save_node_id"],
                "output_node_class_type": spec["save_class_type"],
                "history_descriptor_key": spec["history_descriptor_key"],
                "schema_validation": {
                    "core_revision": CORE_REVISION,
                    "frontend_version": FRONTEND_VERSION,
                    "required_inputs": sorted(spec["save_inputs"]),
                    "output_node_observed": True,
                },
                "inference_executed": False,
                "executable_admission": False,
                "blocked_by": [
                    "verified_local_weight_files",
                    "model_and_component_rights_clearance",
                    "target_gpu_runtime_receipt",
                ],
            }
        )
    manifest: dict[str, object] = {
        "schema": "ProofLaunchComfyUIExecutionWrapperManifestV1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "wrapper_policy": (
            "Official API exports remain unchanged. Each derived wrapper adds exactly one "
            "official ComfyUI output node so /history exposes downloadable evidence."
        ),
        "core_revision": CORE_REVISION,
        "frontend_version": FRONTEND_VERSION,
        "wrapper_count": len(records),
        "records": records,
        "executable_wrapper_count": 0,
        "truth_boundary": (
            "Static output-node wrapping and schema observation do not prove model availability, "
            "rights, prompt validation, GPU execution, output retrieval or creative effect."
        ),
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    atomic_write_bytes(
        OUTPUT_ROOT / "manifest.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT_ROOT / "manifest.json"),
                "wrapper_count": len(records),
                "executable_wrapper_count": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
