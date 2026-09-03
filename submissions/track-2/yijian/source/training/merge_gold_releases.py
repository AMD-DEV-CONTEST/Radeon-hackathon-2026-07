# -*- coding: utf-8 -*-
"""Merge trusted finalized gold packages into one immutable corpus release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

TRAINING_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TRAINING_ROOT))

import expert_corpus  # noqa: E402
import gold_review_workflow as workflow  # noqa: E402
import trusted_katago_artifacts as katago_trust  # noqa: E402
import trusted_source_chain as source_trust  # noqa: E402

WORKSPACE = TRAINING_ROOT / "workspace"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dedupe_rows(rows: list[dict[str, Any]], key: str, label: str) -> list[dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = str(row.get(key) or "")
        workflow.require(identity, f"{label}缺少{key}")
        if identity in values:
            workflow.require(
                workflow.canonical_hash(values[identity]) == workflow.canonical_hash(row),
                f"{label}同一{key}内容冲突：{identity}",
            )
        else:
            values[identity] = row
    return [values[name] for name in sorted(values)]


def find_standalone_source_registry(expected_sha: str, preferred: Path) -> Path:
    candidates = [preferred]
    candidates.extend(WORKSPACE.glob("*/source-chain-registry.json"))
    for candidate in candidates:
        if not candidate.is_file() or sha256_file(candidate) != expected_sha:
            continue
        try:
            source_trust.SourceChainRegistry.load(candidate, expected_sha)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        else:
            return candidate
    raise workflow.WorkflowError(f"找不到带完整manifest的来源registry快照：{expected_sha}")


def copy_source_snapshot(source_registry: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    workflow.copy_source_registry_snapshot(
        source_registry, destination / "source-chain-registry.json"
    )


def katago_leaf_snapshots(registry_path: Path) -> list[tuple[str, Path]]:
    """Return pinned leaf JSONL snapshots; merged bundles may not nest bundles."""
    registry_path = registry_path.resolve()
    try:
        document = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        document = None
    if not isinstance(document, dict) or document.get("schemaVersion") != "gomentor-trusted-katago-registry-bundle-v1":
        snapshot_sha = sha256_file(registry_path)
        katago_trust.load_registry_snapshot(registry_path, expected_sha256=snapshot_sha)
        return [(snapshot_sha, registry_path)]
    rows: list[tuple[str, Path]] = []
    for index, snapshot in enumerate(document.get("snapshots") or [], 1):
        workflow.require(isinstance(snapshot, dict), f"KataGo bundle snapshot {index} is invalid")
        relative = workflow._safe_snapshot_relative(snapshot.get("path"), f"KataGo bundle snapshot {index}")
        child = registry_path.parent / relative
        expected = str(snapshot.get("sha256") or "").lower()
        workflow.require(
            child.is_file() and sha256_file(child) == expected,
            f"KataGo bundle snapshot {index} SHA-256 mismatch",
        )
        loaded = katago_trust.load_registry_snapshot(child, expected_sha256=expected)
        workflow.require(
            loaded.__class__.__name__ != "TrustedKataGoRegistryBundle",
            "nested KataGo registry bundles are not supported",
        )
        rows.append((expected, child))
    workflow.require(rows, "KataGo registry bundle is empty")
    return rows


def merge_packages(package_dirs: list[Path], output_dir: Path) -> dict[str, Any]:
    workflow.require(package_dirs, "至少需要一个定稿包")
    package_dirs = [path.resolve() for path in package_dirs]
    units: list[dict[str, Any]] = []
    approvals: list[dict[str, Any]] = []
    source_snapshots: dict[str, Path] = {}
    katago_snapshots: dict[str, Path] = {}
    reviewer_bytes: bytes | None = None
    inputs = []
    for package in package_dirs:
        required = (
            "teaching-units-v3.jsonl", "review-approvals.jsonl",
            "reviewer-registry.json", "source-chain-registry.json",
            "katago-registry.jsonl", "hash-bundle.json",
        )
        for name in required:
            workflow.require((package / name).is_file(), f"定稿包缺少{name}：{package}")
        bundle = workflow.read_json(package / "hash-bundle.json")
        workflow.require(bundle.get("passed") is True, f"定稿包未通过：{package}")
        for name, expected in (bundle.get("artifacts") or {}).items():
            artifact = package / name
            workflow.require(artifact.is_file(), f"定稿包hash制品缺失：{artifact}")
            workflow.require(sha256_file(artifact) == expected, f"定稿包hash变化：{artifact}")
        for registry_kind, dependencies in (bundle.get("registryDependencies") or {}).items():
            workflow.require(
                registry_kind in {"source", "katago"} and isinstance(dependencies, dict),
                "registry依赖清单无效",
            )
            for relative_value, expected in dependencies.items():
                relative = workflow._safe_snapshot_relative(
                    relative_value, f"{registry_kind} registry依赖"
                )
                dependency = package / relative
                workflow.require(
                    dependency.is_file() and sha256_file(dependency) == expected,
                    f"registry依赖缺失或变化：{dependency}",
                )
        package_reviewer = (package / "reviewer-registry.json").read_bytes()
        if reviewer_bytes is None:
            reviewer_bytes = package_reviewer
        else:
            workflow.require(reviewer_bytes == package_reviewer, "定稿包审核人registry不一致")
        units.extend(workflow.read_jsonl(package / "teaching-units-v3.jsonl"))
        approvals.extend(workflow.read_jsonl(package / "review-approvals.jsonl"))
        source_sha = sha256_file(package / "source-chain-registry.json")
        source_snapshots.setdefault(
            source_sha,
            find_standalone_source_registry(
                source_sha, package / "source-chain-registry.json"
            ),
        )
        for katago_sha, katago_path in katago_leaf_snapshots(
            package / "katago-registry.jsonl"
        ):
            katago_snapshots.setdefault(katago_sha, katago_path)
        inputs.append({
            "path": str(package),
            "hashBundleSha256": sha256_file(package / "hash-bundle.json"),
            "units": int(bundle.get("units") or 0),
        })

    units = dedupe_rows(units, "id", "金标单元")
    approvals = dedupe_rows(approvals, "approvalId", "审核批准")
    unit_ids = {str(unit["id"]) for unit in units}
    approval_units = [str(row.get("unitId") or "") for row in approvals]
    workflow.require(len(approval_units) == len(set(approval_units)), "一个单元存在多个approval")
    workflow.require(set(approval_units) == unit_ids, "approval与金标单元集合不一致")

    output_dir = output_dir.resolve()
    workflow.require(not output_dir.exists(), f"拒绝覆盖已有发布目录：{output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="yijian-gold-release-", dir=output_dir.parent) as temp_name:
        temporary = Path(temp_name)
        units_path = temporary / "teaching-units-v3.jsonl"
        approvals_path = temporary / "review-approvals.jsonl"
        reviewers_path = temporary / "reviewer-registry.json"
        sources_path = temporary / "source-registry-bundle.json"
        katago_path = temporary / "katago-registry-bundle.json"
        workflow.write_jsonl(units_path, units)
        workflow.write_jsonl(approvals_path, approvals)
        reviewers_path.write_bytes(reviewer_bytes or b"")
        source_bundle_rows = []
        for snapshot_sha, source_path in sorted(source_snapshots.items()):
            relative_dir = Path("registry-snapshots") / "source" / snapshot_sha
            copy_source_snapshot(source_path, temporary / relative_dir)
            source_bundle_rows.append({
                "path": str(relative_dir / "source-chain-registry.json").replace("\\", "/"),
                "sha256": snapshot_sha,
            })
        workflow.write_json(sources_path, {
            "schemaVersion": "trusted-source-chain-registry-bundle-v1",
            "snapshots": source_bundle_rows,
        })
        katago_bundle_rows = []
        for snapshot_sha, source_path in sorted(katago_snapshots.items()):
            relative = Path("registry-snapshots") / "katago" / snapshot_sha / "katago-registry.jsonl"
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target)
            katago_bundle_rows.append({
                "path": str(relative).replace("\\", "/"),
                "sha256": snapshot_sha,
            })
        workflow.write_json(katago_path, {
            "schemaVersion": "gomentor-trusted-katago-registry-bundle-v1",
            "snapshots": katago_bundle_rows,
        })
        source_registry = source_trust.SourceChainRegistry.load(
            sources_path, sha256_file(sources_path)
        )
        review_registry = source_trust.HumanReviewRegistry.load(
            reviewers_path, approvals_path,
            sha256_file(reviewers_path), sha256_file(approvals_path),
        )
        katago_registry = katago_trust.load_registry_snapshot(
            katago_path, expected_sha256=sha256_file(katago_path)
        )
        source_policy = expert_corpus.load_sources()
        for unit in units:
            expert_corpus.validate_unit(
                unit, source_policy, source_chain=source_registry,
                review_registry=review_registry, katago_registry=katago_registry,
            )
        manifest = {
            "schemaVersion": workflow.CORPUS_RELEASE_SCHEMA,
            "status": "complete" if len(units) == 64 else "partial_human_review_pending",
            "passed": len(units) == len(approvals),
            "trainingEligible": len(units) == 64,
            "unitCount": len(units),
            "approvalCount": len(approvals),
            "inputs": inputs,
            "artifacts": {
                name: sha256_file(temporary / name)
                for name in (
                    "teaching-units-v3.jsonl", "review-approvals.jsonl",
                    "reviewer-registry.json", "source-registry-bundle.json",
                    "katago-registry-bundle.json",
                )
            },
        }
        workflow.write_json(temporary / "release-manifest.json", manifest)
        os.replace(temporary, output_dir)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    value = merge_packages(args.package_dir, args.output_dir)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
