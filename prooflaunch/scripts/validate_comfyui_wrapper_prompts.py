#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from prooflaunch_remix.files import atomic_write_bytes, sha256_file


ALLOWED_MODEL_INVENTORY_NODE_CLASSES = {
    "CheckpointLoaderSimple",
    "CLIPLoader",
    "DualCLIPLoader",
    "LoraLoaderModelOnly",
    "LTXAVTextEncoderLoader",
    "LTXVAudioVAELoader",
    "LatentUpscaleModelLoader",
    "UNETLoader",
    "VAELoader",
}


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def post_prompt(base_url: str, workflow: dict, timeout_seconds: float) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{base_url}/prompt",
        data=json.dumps(
            {"prompt": workflow, "client_id": "prooflaunch-static-prompt-validation"}
        ).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.loads(error.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8191")
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument(
        "--manifest",
        default=str(
            PROJECT_ROOT / "workflows/comfyui-execution-wrappers-20260801/manifest.json"
        ),
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "evidence/v10/comfyui-wrapper-prompt-validation.json"),
    )
    args = parser.parse_args()
    parsed = urllib.parse.urlsplit(args.base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("--base-url must be a loopback HTTP endpoint")
    base_url = args.base_url.rstrip("/")
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = []
    for record in manifest["records"]:
        wrapper_path = PROJECT_ROOT / record["wrapper_path"]
        wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
        status, response = post_prompt(base_url, wrapper, args.timeout_seconds)
        if status != 400:
            raise SystemExit(
                f"expected fail-closed missing-model validation for {record['workflow_id']}; "
                f"status={status} response={response}"
            )
        if response.get("error", {}).get("type") != "prompt_outputs_failed_validation":
            raise SystemExit(f"unexpected prompt error: {record['workflow_id']}: {response}")
        node_errors = response.get("node_errors")
        if not isinstance(node_errors, dict) or not node_errors:
            raise SystemExit(f"missing model-inventory errors: {record['workflow_id']}")
        if record["output_node_id"] in node_errors:
            raise SystemExit(f"output wrapper failed validation: {record['workflow_id']}")
        blocked_classes = set()
        error_types = set()
        for node_error in node_errors.values():
            class_type = node_error.get("class_type")
            if class_type not in ALLOWED_MODEL_INVENTORY_NODE_CLASSES:
                raise SystemExit(
                    f"non-model structural error in {record['workflow_id']}: {class_type}"
                )
            blocked_classes.add(class_type)
            for error in node_error.get("errors", []):
                error_types.add(error.get("type"))
                if error.get("type") != "value_not_in_list":
                    raise SystemExit(
                        f"unexpected validation error in {record['workflow_id']}: {error}"
                    )
        records.append(
            {
                "workflow_id": record["workflow_id"],
                "wrapper_sha256": sha256_file(wrapper_path),
                "http_status": status,
                "prompt_queued": False,
                "output_wrapper_validation_error": False,
                "blocked_node_classes": sorted(blocked_classes),
                "validation_error_types": sorted(error_types),
                "only_missing_model_inventory_errors_observed": True,
            }
        )
    receipt: dict[str, object] = {
        "schema": "ProofLaunchComfyUIWrapperPromptValidationReceiptV1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "base_url_host": parsed.hostname,
        "wrapper_manifest_sha256": sha256_file(manifest_path),
        "validated_wrapper_count": len(records),
        "records": records,
        "prompt_queued_count": 0,
        "inference_executed": False,
        "gpu_used": False,
        "validation_result": "structure_accepted_blocked_only_by_missing_model_inventory",
        "executable_admission": False,
        "truth_boundary": (
            "The real ComfyUI prompt validator accepted wrapper structure and rejected every "
            "prompt before queueing because declared model files were absent. This is not a "
            "successful prompt, weight, GPU, inference, output or effect receipt."
        ),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    output = Path(args.output).expanduser().resolve()
    try:
        output.relative_to(PROJECT_ROOT)
    except ValueError as error:
        raise SystemExit("--output must remain inside the project root") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(
        output,
        (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "validated_wrapper_count": len(records),
                "prompt_queued_count": 0,
                "validation_result": receipt["validation_result"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
