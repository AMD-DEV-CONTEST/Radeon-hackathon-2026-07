#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from prooflaunch_remix.files import atomic_write_bytes


DEFAULT_WORKFLOWS = ("qwen-image-2512", "ace-step-1.5-text-to-audio")


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", action="append", dest="workflows")
    parser.add_argument(
        "--supply-receipt",
        default=str(PROJECT_ROOT / "evidence/v10/comfyui-weight-supply-chain.json"),
    )
    parser.add_argument(
        "--wrapper-manifest",
        default=str(
            PROJECT_ROOT / "workflows/comfyui-execution-wrappers-20260801/manifest.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "artifacts/comfyui-gpu-handoff-20260801"),
    )
    args = parser.parse_args()
    selected = tuple(args.workflows or DEFAULT_WORKFLOWS)
    if not selected or len(selected) != len(set(selected)):
        raise SystemExit("selected workflows must be unique and non-empty")
    supply_path = Path(args.supply_receipt).expanduser().resolve()
    wrapper_path = Path(args.wrapper_manifest).expanduser().resolve()
    supply = json.loads(supply_path.read_text(encoding="utf-8"))
    wrappers = json.loads(wrapper_path.read_text(encoding="utf-8"))
    available = set(supply["per_workflow"])
    unknown = set(selected) - available
    if unknown:
        raise SystemExit(f"unknown workflow IDs: {sorted(unknown)}")
    not_license_ready = [
        workflow_id
        for workflow_id in selected
        if not supply["per_workflow"][workflow_id]["model_card_license_gate_passed"]
    ]
    if not_license_ready:
        raise SystemExit(
            "GPU handoff refuses legally unresolved workflows: "
            f"{sorted(not_license_ready)}"
        )
    wrapper_by_id = {record["workflow_id"]: record for record in wrappers["records"]}
    downloads = [
        item for item in supply["download_plan"] if item["workflow_id"] in selected
    ]
    expected_downloads = sum(
        supply["per_workflow"][workflow_id]["weight_count"] for workflow_id in selected
    )
    if len(downloads) != expected_downloads:
        raise SystemExit("selected download-plan coverage is incomplete")
    total_size = sum(item["size_bytes"] for item in downloads)
    required_with_headroom = (total_size * 120 + 99) // 100
    confirmation = "+".join(selected)
    plan: dict[str, object] = {
        "schema": "ProofLaunchComfyUIGPUHandoffV1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "selected_workflow_ids": list(selected),
        "supply_receipt_sha256": hashlib.sha256(supply_path.read_bytes()).hexdigest(),
        "wrapper_manifest_sha256": hashlib.sha256(wrapper_path.read_bytes()).hexdigest(),
        "selection_reason": (
            "Fastest rights-legible demo closure: campaign image plus original music. "
            "Wan and LTX remain outside this handoff until their component/legal gates close."
        ),
        "download_count": len(downloads),
        "total_size_bytes": total_size,
        "required_free_bytes_with_20_percent_headroom": required_with_headroom,
        "downloads": downloads,
        "execution_wrappers": [
            {
                "workflow_id": workflow_id,
                "path": wrapper_by_id[workflow_id]["wrapper_path"],
                "sha256": wrapper_by_id[workflow_id]["wrapper_sha256"],
                "output_node_id": wrapper_by_id[workflow_id]["output_node_id"],
            }
            for workflow_id in selected
        ],
        "required_environment": {
            "COMFYUI_MODELS_ROOT": "absolute path to the active ComfyUI models directory",
            "PROOFLAUNCH_CONFIRM_DOWNLOAD": confirmation,
        },
        "post_download_verification_command": (
            "PYTHONPATH=src ./.venv/bin/python scripts/verify_comfyui_weight_supply_chain.py "
            "--models-root \"$COMFYUI_MODELS_ROOT\""
        ),
        "execution_admission_after_download": False,
        "remaining_gates": [
            "target Radeon or other GPU runtime preflight",
            "independent local SHA256 verification",
            "real prompt execution and artifact receipt",
            "blind human effect review",
            "qualifying Radeon-local key inference for competition evidence",
        ],
        "truth_boundary": (
            "This handoff is a deterministic download and verification plan. It does not "
            "download files, authorize model use, execute inference or prove output quality."
        ),
    }
    plan["plan_sha256"] = canonical_sha256(plan)
    output_dir = Path(args.output_dir).expanduser().resolve()
    try:
        output_dir.relative_to(PROJECT_ROOT)
    except ValueError as error:
        raise SystemExit("--output-dir must remain inside the project root") from error
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(
        output_dir / "handoff.json",
        (json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        ': "${COMFYUI_MODELS_ROOT:?Set COMFYUI_MODELS_ROOT to the active ComfyUI models directory}"',
        ': "${PROOFLAUNCH_CONFIRM_DOWNLOAD:?Set PROOFLAUNCH_CONFIRM_DOWNLOAD to the exact sealed workflow selection}"',
        f"EXPECTED_CONFIRMATION={shlex.quote(confirmation)}",
        'if [[ "$PROOFLAUNCH_CONFIRM_DOWNLOAD" != "$EXPECTED_CONFIRMATION" ]]; then',
        '  echo "Confirmation mismatch; refusing large model download." >&2',
        "  exit 2",
        "fi",
        'MODELS_ROOT="$(cd "$COMFYUI_MODELS_ROOT" 2>/dev/null && pwd -P)"',
        'if [[ -z "$MODELS_ROOT" || "$MODELS_ROOT" == "/" || "$MODELS_ROOT" == "$HOME" ]]; then',
        '  echo "Unsafe COMFYUI_MODELS_ROOT." >&2',
        "  exit 2",
        "fi",
        f"REQUIRED_BYTES={required_with_headroom}",
        'AVAILABLE_KIB="$(df -Pk "$MODELS_ROOT" | awk \'NR==2 {print $4}\')"',
        'AVAILABLE_BYTES="$((AVAILABLE_KIB * 1024))"',
        'if (( AVAILABLE_BYTES < REQUIRED_BYTES )); then',
        '  echo "Insufficient free space: need $REQUIRED_BYTES bytes including headroom." >&2',
        "  exit 3",
        "fi",
        "",
        "download_one() {",
        '  local url="$1" relative="$2" expected_size="$3" expected_sha="$4"',
        '  local destination="$MODELS_ROOT/$relative" partial="$MODELS_ROOT/$relative.partial"',
        '  mkdir -p "$(dirname "$destination")"',
        '  if [[ -f "$destination" ]]; then',
        '    local existing_size existing_sha',
        '    existing_size="$(stat -c %s "$destination")"',
        '    existing_sha="$(sha256sum "$destination" | awk \'{print $1}\')"',
        '    if [[ "$existing_size" == "$expected_size" && "$existing_sha" == "$expected_sha" ]]; then',
        '      echo "verified existing $relative"',
        "      return",
        "    fi",
        '    echo "Existing file failed sealed hash: $relative" >&2',
        "    exit 4",
        "  fi",
        '  curl --fail --location --retry 5 --retry-all-errors --continue-at - --output "$partial" "$url"',
        '  local actual_size actual_sha',
        '  actual_size="$(stat -c %s "$partial")"',
        '  actual_sha="$(sha256sum "$partial" | awk \'{print $1}\')"',
        '  if [[ "$actual_size" != "$expected_size" || "$actual_sha" != "$expected_sha" ]]; then',
        '    echo "Downloaded file failed sealed size/hash: $relative" >&2',
        "    exit 5",
        "  fi",
        '  mv "$partial" "$destination"',
        '  echo "installed $relative"',
        "}",
        "",
    ]
    for item in downloads:
        relative = f"{item['destination']}"
        lines.append(
            "download_one "
            f"{shlex.quote(item['pinned_url'])} {shlex.quote(relative)} "
            f"{item['size_bytes']} {item['sha256']}"
        )
    lines.extend(
        [
            "",
            'echo "All selected model files passed sealed SHA256 verification."',
        ]
    )
    shell_path = output_dir / "download-and-verify.sh"
    atomic_write_bytes(shell_path, ("\n".join(lines) + "\n").encode("utf-8"))
    shell_path.chmod(0o700)
    print(
        json.dumps(
            {
                "output": str(output_dir / "handoff.json"),
                "download_script": str(shell_path),
                "selected_workflow_ids": selected,
                "download_count": len(downloads),
                "total_size_bytes": total_size,
                "required_free_bytes_with_20_percent_headroom": required_with_headroom,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
