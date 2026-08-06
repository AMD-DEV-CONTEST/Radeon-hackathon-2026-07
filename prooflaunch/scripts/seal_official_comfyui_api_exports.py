#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text


MANIFEST = ROOT / "workflows/comfyui-official-20260801/manifest.json"
EXPECTED_CORE_REVISION = "2881e6161081439b1c3fb3b6c1f51b3d272da710"
EXPECTED_FRONTEND_VERSION = "1.47.11"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema") != "ProofLaunchOfficialComfyUIWorkflowCaptureV1":
        raise SystemExit("official workflow manifest schema is unsupported")
    records = manifest.get("workflows")
    if not isinstance(records, list) or len(records) != manifest.get("workflow_count"):
        raise SystemExit("official workflow manifest records are invalid")

    for record in records:
        workflow_id = record.get("workflow_id")
        if not isinstance(workflow_id, str) or not workflow_id:
            raise SystemExit("workflow ID is invalid")
        directory = MANIFEST.parent
        api_path = directory / f"{workflow_id}.api.json"
        receipt_path = directory / f"{workflow_id}.api-export-receipt.json"
        if not api_path.is_file() or not receipt_path.is_file():
            raise SystemExit(f"{workflow_id}: API export or receipt is missing")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        expected_receipt = {
            "schema": "ProofLaunchOfficialComfyUIApiExportReceiptV1",
            "method": "official_frontend_app.loadGraphData_then_app.graphToPrompt",
            "source_blueprint": Path(record["local_path"]).name,
            "source_blueprint_sha256": record["sha256"],
            "output_api_workflow": api_path.name,
            "output_api_workflow_sha256": _sha256(api_path),
            "comfyui_core_revision": EXPECTED_CORE_REVISION,
            "comfyui_frontend_version": EXPECTED_FRONTEND_VERSION,
            "inference_executed": False,
            "models_loaded": False,
            "gpu_used": False,
            "missing_node_count": 0,
        }
        for key, expected in expected_receipt.items():
            if receipt.get(key) != expected:
                raise SystemExit(
                    f"{workflow_id}: API export receipt mismatch for {key}"
                )
        try:
            api_workflow = json.loads(api_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise SystemExit(f"{workflow_id}: API workflow is invalid JSON") from error
        if (
            not isinstance(api_workflow, dict)
            or len(api_workflow) != receipt.get("output_node_count")
            or not api_workflow
        ):
            raise SystemExit(f"{workflow_id}: API workflow node count is invalid")
        if any(
            not isinstance(node, dict)
            or not isinstance(node.get("class_type"), str)
            or not node["class_type"]
            or not isinstance(node.get("inputs"), dict)
            for node in api_workflow.values()
        ):
            raise SystemExit(f"{workflow_id}: API workflow contains invalid nodes")
        record.update(
            {
                "api_format_exported": True,
                "api_local_path": _relative(api_path),
                "api_sha256": receipt["output_api_workflow_sha256"],
                "api_output_node_count": receipt["output_node_count"],
                "api_export_receipt_path": _relative(receipt_path),
                "api_export_method": receipt["method"],
                "api_export_core_revision": receipt["comfyui_core_revision"],
                "api_export_frontend_version": receipt[
                    "comfyui_frontend_version"
                ],
                "executable_admission": False,
                "blocked_by": [
                    "immutable_model_weight_revisions",
                    "weight_sha256_receipts",
                    "model_license_and_commercial_rights_receipts",
                    "target_gpu_runtime_receipt",
                ],
                "next_action": (
                    "Resolve every mutable model URL to an immutable revision, hash the "
                    "downloaded weights, verify model-specific rights, then validate this "
                    "already-exported API workflow on the target GPU."
                ),
            }
        )

    manifest["api_format_export_count"] = len(records)
    manifest["executable_workflow_count"] = sum(
        bool(record.get("executable_admission")) for record in records
    )
    manifest["truth_boundary"] = (
        "These are exact official ComfyUI blueprints plus API-format exports produced by "
        "the pinned official frontend. No model weights were loaded and no inference or GPU "
        "execution occurred. Mutable model URLs, weight hashes, model-specific rights and "
        "target-GPU receipts still block executable admission and all quality claims."
    )
    manifest.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    atomic_write_text(
        MANIFEST,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    MANIFEST.chmod(0o600)
    print(
        json.dumps(
            {
                "manifest": str(MANIFEST),
                "api_format_export_count": manifest["api_format_export_count"],
                "executable_workflow_count": manifest[
                    "executable_workflow_count"
                ],
                "manifest_sha256": manifest["manifest_sha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
