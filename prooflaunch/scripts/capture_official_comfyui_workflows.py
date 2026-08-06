#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_bytes, atomic_write_text


REPOSITORY = "https://github.com/Comfy-Org/workflow_templates"
REVISION = "1b3bdd46c945d54d893a3b43692d5963608fb7d4"
TARGETS = {
    "qwen-image-2512": "blueprints/text_to_image_qwen_image_2512.json",
    "ltx-2.3-text-to-video": "blueprints/text_to_video_ltx_2_3.json",
    "wan2.2-text-to-video": "blueprints/text_to_video_wan_2_2.json",
    "ace-step-1.5-text-to-audio": "blueprints/text_to_audio_ace_step_1_5.json",
}


def _read_blob(git_dir: Path, source_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(git_dir), "show", f"{REVISION}:{source_path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"cannot read {source_path} from frozen repository: "
            + completed.stderr.decode("utf-8", errors="replace")[-500:]
        )
    return completed.stdout


def _model_metadata(value: object) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    if isinstance(value, dict):
        models = value.get("models")
        if isinstance(models, list):
            for model in models:
                if isinstance(model, dict):
                    found.append(
                        {
                            key: model.get(key)
                            for key in ("name", "url", "directory")
                            if model.get(key) is not None
                        }
                    )
        for child in value.values():
            found.extend(_model_metadata(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_model_metadata(child))
    unique: dict[str, dict[str, object]] = {}
    for item in found:
        identity = json.dumps(item, sort_keys=True, separators=(",", ":"))
        unique[identity] = item
    return list(unique.values())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-git-dir", required=True)
    parser.add_argument(
        "--output",
        default=str(ROOT / "workflows/comfyui-official-20260801"),
    )
    args = parser.parse_args()
    source_git_dir = Path(args.source_git_dir).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    try:
        output.relative_to(ROOT)
    except ValueError as error:
        raise SystemExit("--output must remain inside the project root") from error
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output directory must be empty")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)

    records: list[dict[str, object]] = []
    for workflow_id, source_path in TARGETS.items():
        body = _read_blob(source_git_dir, source_path)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as error:
            raise SystemExit(f"{source_path} is invalid JSON: {error}") from error
        subgraphs = payload.get("definitions", {}).get("subgraphs", [])
        if not isinstance(subgraphs, list) or len(subgraphs) != 1:
            raise SystemExit(f"{source_path} must contain exactly one official subgraph")
        subgraph = subgraphs[0]
        inputs = subgraph.get("inputs", [])
        outputs = subgraph.get("outputs", [])
        if not inputs or not outputs:
            raise SystemExit(f"{source_path} has no declared app inputs/outputs")
        destination = output / f"{workflow_id}.blueprint.json"
        atomic_write_bytes(destination, body)
        destination.chmod(0o600)
        records.append(
            {
                "workflow_id": workflow_id,
                "source_path": source_path,
                "source_url": f"{REPOSITORY}/blob/{REVISION}/{source_path}",
                "local_path": str(destination.relative_to(ROOT)),
                "sha256": hashlib.sha256(body).hexdigest(),
                "subgraph_name": subgraph.get("name"),
                "inputs": [
                    {"name": item.get("name"), "type": item.get("type")}
                    for item in inputs
                    if isinstance(item, dict)
                ],
                "outputs": [
                    {"name": item.get("name"), "type": item.get("type")}
                    for item in outputs
                    if isinstance(item, dict)
                ],
                "declared_models": _model_metadata(payload),
                "source_format": "comfyui_native_subgraph_blueprint",
                "api_format_exported": False,
                "executable_admission": False,
                "next_action": (
                    "Load this exact blueprint in the pinned ComfyUI instance, export "
                    "API Format through the official UI, then admit the exported JSON "
                    "only after node, model-weight, license, and target-GPU checks."
                ),
            }
        )

    manifest_basis = {
        "schema": "ProofLaunchOfficialComfyUIWorkflowCaptureV1",
        "repository_url": REPOSITORY,
        "revision": REVISION,
        "source_license": "MIT",
        "license_locator": f"{REPOSITORY}/blob/{REVISION}/LICENSE",
        "workflow_count": len(records),
        "workflows": records,
        "api_format_export_count": 0,
        "executable_workflow_count": 0,
        "truth_boundary": (
            "These files are exact official ComfyUI blueprint captures. They are not API "
            "workflow exports, downloaded model weights, GPU executions, generated assets, "
            "model-license receipts, or quality evidence."
        ),
    }
    manifest_sha256 = hashlib.sha256(
        json.dumps(manifest_basis, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest = {**manifest_basis, "manifest_sha256": manifest_sha256}
    manifest_path = output / "manifest.json"
    atomic_write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    manifest_path.chmod(0o600)
    print(json.dumps({"manifest": str(manifest_path), **manifest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
