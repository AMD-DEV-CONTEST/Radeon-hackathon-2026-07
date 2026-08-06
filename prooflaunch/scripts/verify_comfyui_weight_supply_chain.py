#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from prooflaunch_remix.files import atomic_write_bytes


SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
DECLARED_URL = re.compile(
    r"^https://huggingface\.co/(?P<repo>[^/]+/[^/]+)/resolve/main/(?P<path>.+)$"
)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def pinned_url(repository: str, revision: str, path: str) -> str:
    encoded_path = "/".join(quote(part, safe="") for part in path.split("/"))
    return f"https://huggingface.co/{repository}/resolve/{revision}/{encoded_path}"


def canonical_json_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify immutable metadata and optionally local files for official ComfyUI workflows."
    )
    parser.add_argument(
        "--supply-chain",
        default=str(PROJECT_ROOT / "config/comfyui_weight_supply_chain_v1.json"),
    )
    parser.add_argument(
        "--workflow-manifest",
        default=str(PROJECT_ROOT / "workflows/comfyui-official-20260801/manifest.json"),
    )
    parser.add_argument("--models-root")
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "evidence/v10/comfyui-weight-supply-chain.json"),
    )
    args = parser.parse_args()

    supply_path = Path(args.supply_chain).expanduser().resolve()
    workflow_path = Path(args.workflow_manifest).expanduser().resolve()
    supply = json.loads(supply_path.read_text(encoding="utf-8"))
    workflow_manifest = json.loads(workflow_path.read_text(encoding="utf-8"))

    repositories = supply["repositories"]
    weights = supply["weights"]
    if not repositories or not weights:
        raise SystemExit("supply chain must include repositories and weights")
    for repository, record in repositories.items():
        if not REVISION.fullmatch(record["revision"]):
            raise SystemExit(f"repository revision is not immutable: {repository}")
        if record["rights_status"] == "cleared":
            raise SystemExit(
                f"rights_status may not claim broad clearance from model-card metadata: {repository}"
            )

    expected: dict[tuple[str, str, str], dict[str, object]] = {}
    for workflow in workflow_manifest["workflows"]:
        for model in workflow["declared_models"]:
            match = DECLARED_URL.fullmatch(model["url"])
            if not match:
                raise SystemExit(f"unexpected mutable model URL: {model['url']}")
            key = (workflow["workflow_id"], match.group("repo"), match.group("path"))
            expected[key] = model

    observed: dict[tuple[str, str, str], dict[str, object]] = {}
    destination_counts: Counter[tuple[str, str]] = Counter()
    for weight in weights:
        repository = weight["repository"]
        if repository not in repositories:
            raise SystemExit(f"weight references unknown repository: {repository}")
        if not SHA256.fullmatch(weight["sha256"]):
            raise SystemExit(f"invalid SHA256 for {weight['name']}")
        if weight["size_bytes"] <= 0:
            raise SystemExit(f"invalid size for {weight['name']}")
        if Path(weight["path"]).name != weight["name"]:
            raise SystemExit(f"weight path/name mismatch: {weight['path']}")
        key = (weight["workflow_id"], repository, weight["path"])
        if key in observed:
            raise SystemExit(f"duplicate weight record: {key}")
        observed[key] = weight
        destination_counts[(weight["directory"], weight["name"])] += 1

    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    if missing or extra:
        raise SystemExit(f"weight coverage mismatch; missing={missing}, extra={extra}")
    collisions = [key for key, count in destination_counts.items() if count > 1]
    if collisions:
        raise SystemExit(f"ComfyUI destination collisions: {collisions}")

    per_workflow: dict[str, dict[str, int]] = defaultdict(
        lambda: {"weight_count": 0, "total_size_bytes": 0}
    )
    workflow_repositories: dict[str, set[str]] = defaultdict(set)
    download_plan = []
    local_checks = []
    models_root = Path(args.models_root).expanduser().resolve() if args.models_root else None
    for weight in weights:
        repository = weight["repository"]
        revision = repositories[repository]["revision"]
        remote = pinned_url(repository, revision, weight["path"])
        destination = Path(weight["directory"]) / weight["name"]
        per_workflow[weight["workflow_id"]]["weight_count"] += 1
        per_workflow[weight["workflow_id"]]["total_size_bytes"] += weight["size_bytes"]
        workflow_repositories[weight["workflow_id"]].add(repository)
        download_plan.append(
            {
                "workflow_id": weight["workflow_id"],
                "repository": repository,
                "revision": revision,
                "pinned_url": remote,
                "destination": destination.as_posix(),
                "size_bytes": weight["size_bytes"],
                "sha256": weight["sha256"],
            }
        )
        if models_root is not None:
            local_path = models_root / destination
            exists = local_path.is_file()
            size_matches = exists and local_path.stat().st_size == weight["size_bytes"]
            observed_hash = sha256_path(local_path) if size_matches else None
            local_checks.append(
                {
                    "workflow_id": weight["workflow_id"],
                    "destination": destination.as_posix(),
                    "exists": exists,
                    "size_matches": size_matches,
                    "observed_sha256": observed_hash,
                    "sha256_matches": observed_hash == weight["sha256"],
                }
            )

    unresolved_repositories = sorted(
        repository
        for repository, record in repositories.items()
        if record["rights_status"] != "card_license_observed"
    )
    installed_verified = sum(check["sha256_matches"] for check in local_checks)
    all_local_weights_verified = bool(local_checks) and installed_verified == len(weights)
    per_workflow_receipts = {}
    for workflow_id, summary in sorted(per_workflow.items()):
        required_repositories = sorted(workflow_repositories[workflow_id])
        workflow_local_checks = [
            check for check in local_checks if check["workflow_id"] == workflow_id
        ]
        locally_verified_weight_count = sum(
            check["sha256_matches"] for check in workflow_local_checks
        )
        per_workflow_receipts[workflow_id] = {
            **summary,
            "repository_count": len(required_repositories),
            "repositories": required_repositories,
            "model_card_license_gate_passed": all(
                repositories[repository]["rights_status"] == "card_license_observed"
                for repository in required_repositories
            ),
            "locally_verified_weight_count": locally_verified_weight_count,
            "all_local_weights_verified": (
                bool(workflow_local_checks)
                and locally_verified_weight_count == summary["weight_count"]
            ),
        }
    model_card_license_ready_workflow_ids = sorted(
        workflow_id
        for workflow_id, summary in per_workflow_receipts.items()
        if summary["model_card_license_gate_passed"]
    )
    receipt: dict[str, object] = {
        "schema": "ProofLaunchComfyUIWeightSupplyChainReceiptV1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "supply_chain_sha256": sha256_path(supply_path),
        "workflow_manifest_sha256": sha256_path(workflow_path),
        "repository_count": len(repositories),
        "weight_count": len(weights),
        "immutable_repository_revision_count": len(repositories),
        "server_reported_weight_sha256_count": len(weights),
        "total_size_bytes": sum(weight["size_bytes"] for weight in weights),
        "per_workflow": per_workflow_receipts,
        "model_card_license_ready_workflow_ids": model_card_license_ready_workflow_ids,
        "unresolved_or_legal_review_repository_count": len(unresolved_repositories),
        "unresolved_or_legal_review_repositories": unresolved_repositories,
        "download_plan": download_plan,
        "models_root": str(models_root) if models_root else None,
        "local_file_checks": local_checks,
        "installed_verified_weight_count": installed_verified,
        "all_local_weights_verified": all_local_weights_verified,
        "rights_gate_passed": not unresolved_repositories,
        "target_gpu_runtime_gate_passed": False,
        "executable_admission": False,
        "blocked_by": [
            "unresolved_or_legal_review_model_component_rights",
            "verified_local_weight_files",
            "target_gpu_runtime_receipt",
            "blind_human_effect_gate"
        ],
        "truth_boundary": (
            "This receipt verifies exact coverage, immutable repository revisions and server-"
            "reported LFS hashes/sizes. It does not download weights, independently hash absent "
            "files, clear rights, execute inference, prove Radeon support or prove creative effect."
        ),
    }
    receipt["receipt_sha256"] = canonical_json_sha256(receipt)
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
                "weight_count": receipt["weight_count"],
                "total_size_bytes": receipt["total_size_bytes"],
                "unresolved_or_legal_review_repository_count": receipt[
                    "unresolved_or_legal_review_repository_count"
                ],
                "installed_verified_weight_count": installed_verified,
                "executable_admission": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
