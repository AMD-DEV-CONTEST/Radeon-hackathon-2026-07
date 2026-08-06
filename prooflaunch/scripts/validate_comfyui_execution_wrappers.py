#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from prooflaunch_remix.files import atomic_write_bytes, sha256_file


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def fetch_json(base_url: str, path: str, timeout_seconds: float) -> dict:
    request = urllib.request.Request(f"{base_url}{path}", method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"ComfyUI returned non-object JSON for {path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8191")
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument(
        "--manifest",
        default=str(
            PROJECT_ROOT / "workflows/comfyui-execution-wrappers-20260801/manifest.json"
        ),
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "evidence/v10/comfyui-execution-wrapper-schema.json"),
    )
    args = parser.parse_args()
    parsed = urllib.parse.urlsplit(args.base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("--base-url must be a loopback HTTP endpoint")
    base_url = args.base_url.rstrip("/")
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_by_class = {}
    validation_records = []
    for record in manifest["records"]:
        class_type = record["output_node_class_type"]
        if class_type not in schema_by_class:
            response = fetch_json(
                base_url,
                f"/object_info/{urllib.parse.quote(class_type, safe='')}",
                args.timeout_seconds,
            )
            node_schema = response.get(class_type)
            if not isinstance(node_schema, dict):
                raise SystemExit(f"ComfyUI output-node schema missing: {class_type}")
            schema_by_class[class_type] = node_schema
        node_schema = schema_by_class[class_type]
        required = set(node_schema.get("input", {}).get("required", {}))
        supplied = set(record["schema_validation"]["required_inputs"])
        if required != supplied:
            raise SystemExit(
                f"output-node input schema drift for {record['workflow_id']}: "
                f"required={sorted(required)} supplied={sorted(supplied)}"
            )
        if node_schema.get("output_node") is not True:
            raise SystemExit(f"ComfyUI node is not an output node: {class_type}")
        wrapper_path = PROJECT_ROOT / record["wrapper_path"]
        wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
        output_node = wrapper.get(record["output_node_id"])
        if not isinstance(output_node, dict) or output_node.get("class_type") != class_type:
            raise SystemExit(f"sealed wrapper output node drift: {record['workflow_id']}")
        validation_records.append(
            {
                "workflow_id": record["workflow_id"],
                "wrapper_sha256": sha256_file(wrapper_path),
                "output_node_id": record["output_node_id"],
                "output_node_class_type": class_type,
                "required_inputs": sorted(required),
                "output_node": True,
                "schema_sha256": canonical_sha256(node_schema),
            }
        )
    receipt: dict[str, object] = {
        "schema": "ProofLaunchComfyUIExecutionWrapperSchemaReceiptV1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "base_url_host": parsed.hostname,
        "core_revision_expected": manifest["core_revision"],
        "frontend_version_expected": manifest["frontend_version"],
        "wrapper_manifest_sha256": sha256_file(manifest_path),
        "validated_wrapper_count": len(validation_records),
        "validation_records": validation_records,
        "prompt_submitted": False,
        "inference_executed": False,
        "target_gpu_used": False,
        "executable_admission": False,
        "truth_boundary": (
            "The pinned CPU-only ComfyUI runtime confirmed the exact output-node schemas. "
            "No prompt was submitted and this is not model, GPU, output or effect evidence."
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
                "validated_wrapper_count": len(validation_records),
                "prompt_submitted": False,
                "inference_executed": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
