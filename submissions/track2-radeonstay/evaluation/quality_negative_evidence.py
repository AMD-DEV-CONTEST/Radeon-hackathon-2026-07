#!/usr/bin/env python3
"""Build and independently verify an A-only quality-negative evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from evaluation.compare_benchmarks import (
        _parse_utc_instant,
        normalized_report_service_configuration,
        runtime_gpu_summary,
        validate_quality_negative_report,
        validate_request_configuration,
        validate_retrieval_report,
    )
    from evaluation.configuration import (
        request_configuration_sha256,
        service_configuration_sha256,
    )
    from evaluation.runtime_binding_evidence import (
        load_runtime_instance,
        validate_report_runtime_binding,
    )
except ModuleNotFoundError:  # Direct ``python evaluation/quality_negative_evidence.py``.
    from compare_benchmarks import (  # type: ignore[no-redef]
        _parse_utc_instant,
        normalized_report_service_configuration,
        runtime_gpu_summary,
        validate_quality_negative_report,
        validate_request_configuration,
        validate_retrieval_report,
    )
    from configuration import (  # type: ignore[no-redef]
        request_configuration_sha256,
        service_configuration_sha256,
    )
    from runtime_binding_evidence import (  # type: ignore[no-redef]
        load_runtime_instance,
        validate_report_runtime_binding,
    )

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")
TREE_RE = re.compile(r"^[0-9a-f]{40,64}$")
GPU_UNIQUE_ID_RE = re.compile(r"^0x[0-9a-f]+$")
A_SERVICE_CONFIGURATION_FIELDS = {
    "experiment",
    "ctx",
    "parallel",
    "batch",
    "ubatch",
    "flash_attn",
    "gpu_layers",
    "cache_type_k",
    "cache_type_v",
    "log_verbosity",
}
FILE_NAMES = {
    "retrieval": "retrieval.json",
    "quality": "agent-quality.json",
    "monitor": "rocm-monitor.log",
    "server": "llama-server.log",
    "runtime_instance": "runtime-instance.json",
}
MANIFEST_FIELDS = {
    "schema_version",
    "evidence_type",
    "status",
    "label",
    "run_id",
    "created_at_utc",
    "commit",
    "project_tree",
    "source_tree_sha256",
    "request_configuration",
    "request_configuration_sha256",
    "service_configuration",
    "service_configuration_sha256",
    "quality_score",
    "quality_maximum_score",
    "failed_quality_gates",
    "model_sha256",
    "llama_server_sha256",
    "runtime_instance_sha256",
    "active_gpu_unique_ids",
    "active_gpu_identity_sha256",
    "offloaded_model_layers",
    "gpu_activity_verified",
    "files",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return value


def _single_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)=([^\s]+)", line)
        if match is None:
            continue
        key, value = match.groups()
        if key in values and values[key] != value:
            raise ValueError(f"Evidence log contains conflicting {key} values")
        values[key] = value
    return values


def _strict_a_service_configuration(report: dict[str, Any]) -> dict[str, int | str]:
    raw = report.get("service_configuration")
    if not isinstance(raw, dict) or set(raw) != A_SERVICE_CONFIGURATION_FIELDS:
        raise ValueError(
            "Quality-negative A must declare the complete explicit service "
            "configuration, including ctx"
        )
    if raw.get("experiment") != "A":
        raise ValueError("Quality-negative service configuration is not experiment A")
    service = normalized_report_service_configuration(
        report,
        "negative A service configuration",
    )
    if not (
        service["parallel"] == 1
        and service["batch"] == 256
        and service["ubatch"] == 64
        and service["flash_attn"] == "off"
        and service["gpu_layers"] == 999
        and service["cache_type_k"] == service["cache_type_v"] == "f16"
        and service["log_verbosity"] == 5
    ):
        raise ValueError("Quality-negative service configuration is not matrix row A")
    return service


def _active_gpu_identity_sha256(value: Any, label: str) -> str:
    if not (
        isinstance(value, list)
        and value
        and all(
            isinstance(item, str) and GPU_UNIQUE_ID_RE.fullmatch(item) is not None
            for item in value
        )
        and value == sorted(set(value))
    ):
        raise ValueError(f"{label} must contain sorted unique Radeon GPU IDs")
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _validate_evidence(
    *,
    retrieval_path: Path,
    quality_path: Path,
    monitor_path: Path,
    server_path: Path,
    runtime_instance_path: Path,
    expected_run_id: str,
    expected_commit: str,
    expected_project_tree: str,
) -> dict[str, Any]:
    retrieval = _load_json(retrieval_path, "negative retrieval report")
    quality = _load_json(quality_path, "negative quality report")
    validate_retrieval_report(retrieval, "negative A retrieval")
    recomputed = validate_quality_negative_report(quality, "negative A quality")
    if quality.get("run_id") != expected_run_id or retrieval.get("run_id") != expected_run_id:
        raise ValueError("Negative reports do not match the A run ID")
    provenance = quality.get("provenance")
    retrieval_provenance = retrieval.get("provenance")
    source_tree_sha256 = (
        provenance.get("source_tree_sha256") if isinstance(provenance, dict) else None
    )
    if not (
        isinstance(provenance, dict)
        and isinstance(retrieval_provenance, dict)
        and provenance.get("commit") == expected_commit
        and provenance.get("project_tree") == expected_project_tree
        and isinstance(source_tree_sha256, str)
        and SHA256_RE.fullmatch(source_tree_sha256) is not None
        and all(
            retrieval_provenance.get(field) == provenance.get(field)
            for field in ("commit", "project_tree", "source_tree_sha256")
        )
    ):
        raise ValueError("Negative quality source binding differs from frozen C2")
    request = validate_request_configuration(quality, "negative A")
    if request != {
        "thinking_enabled": True,
        "schema_constrained": True,
        "fused_plan_evidence": False,
    }:
        raise ValueError("Only the exact A request profile may be a quality negative")
    service = _strict_a_service_configuration(quality)
    instance = load_runtime_instance(
        runtime_instance_path,
        expected_run_id=expected_run_id,
    )
    validate_report_runtime_binding(
        quality,
        expected_manifest_sha256=instance.manifest_sha256,
        report_kind="quality",
        label="negative A quality",
    )
    if instance.payload["service_configuration_sha256"] != service_configuration_sha256(
        service,
        "negative A service configuration",
    ):
        raise ValueError("Negative A runtime instance differs from its service profile")
    artifacts = quality.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("Negative quality report lacks artifact hashes")
    model_sha256 = artifacts.get("model_file_sha256")
    llama_sha256 = artifacts.get("llama_server_sha256")
    if not (
        isinstance(model_sha256, str)
        and SHA256_RE.fullmatch(model_sha256)
        and isinstance(llama_sha256, str)
        and SHA256_RE.fullmatch(llama_sha256)
        and instance.payload["model_sha256"] == model_sha256
        and instance.payload["executable_sha256"] == llama_sha256
    ):
        raise ValueError("Negative A artifact hashes do not match the runtime instance")
    server = _single_values(server_path)
    if not (
        server.get("evidence_run_id") == expected_run_id
        and server.get("evidence_log_status") == "complete"
        and server.get("llama_server_exit_code") in {"0", "143"}
        and server.get("process_binding_valid") == "true"
        and server.get("listen_socket_binding_valid") == "true"
        and server.get("runtime_instance_manifest_sha256")
        == instance.manifest_sha256
        and server.get("model_sha256_at_start") == model_sha256
        and server.get("llama_server_sha256_at_start") == llama_sha256
    ):
        raise ValueError("Negative A server lifecycle evidence is incomplete")
    monitor = _single_values(monitor_path)
    try:
        completed_samples = int(monitor.get("completed_samples", "0"))
    except ValueError as exc:
        raise ValueError("Negative A monitor sample count is invalid") from exc
    if not (
        monitor.get("schema_version") == "1"
        and monitor.get("run_id") == expected_run_id
        and monitor.get("status") == "complete"
        and completed_samples >= 2
    ):
        raise ValueError("Negative A ROCm monitor evidence is incomplete")
    runtime = runtime_gpu_summary(
        server_path,
        monitor_path,
        "negative A",
        required_windows={
            "agent_quality": (
                _parse_utc_instant(
                    quality.get("started_at_utc"),
                    "negative A quality start",
                ),
                _parse_utc_instant(
                    quality.get("completed_at_utc"),
                    "negative A quality end",
                ),
            )
        },
        expected_run_id=expected_run_id,
        expected_sample_count=completed_samples,
        require_device_identity=True,
    )
    active_gpu_unique_ids = runtime.get("common_active_gpu_unique_ids")
    active_gpu_identity_sha256 = _active_gpu_identity_sha256(
        active_gpu_unique_ids,
        "negative A active GPU identity",
    )
    failed_gates = sorted(
        key for key, passed in recomputed["gates"].items() if passed is not True
    )
    return {
        "request_configuration": request,
        "request_configuration_sha256": request_configuration_sha256(
            request,
            "negative A request configuration",
        ),
        "service_configuration": service,
        "service_configuration_sha256": service_configuration_sha256(
            service,
            "negative A service configuration",
        ),
        "quality_score": recomputed["metrics"]["total_score"],
        "quality_maximum_score": recomputed["metrics"]["maximum_score"],
        "failed_quality_gates": failed_gates,
        "source_tree_sha256": source_tree_sha256,
        "model_sha256": model_sha256,
        "llama_server_sha256": llama_sha256,
        "runtime_instance_sha256": instance.manifest_sha256,
        "active_gpu_unique_ids": active_gpu_unique_ids,
        "active_gpu_identity_sha256": active_gpu_identity_sha256,
        "offloaded_model_layers": "41/41",
        "gpu_activity_verified": True,
    }


def load_quality_negative_bundle(
    manifest_path: Path,
    *,
    expected_label: str = "A",
) -> dict[str, Any]:
    manifest = _load_json(manifest_path, "quality-negative manifest")
    if set(manifest) != MANIFEST_FIELDS or not (
        manifest.get("schema_version") == 1
        and manifest.get("evidence_type") == "radeonstay-quality-negative"
        and manifest.get("status") == "quality_rejected"
        and manifest.get("label") == expected_label == "A"
    ):
        raise ValueError("Quality-negative manifest schema or status is invalid")
    run_id = manifest.get("run_id")
    commit = manifest.get("commit")
    project_tree = manifest.get("project_tree")
    if not (
        isinstance(run_id, str)
        and RUN_ID_RE.fullmatch(run_id)
        and isinstance(commit, str)
        and COMMIT_RE.fullmatch(commit)
        and isinstance(project_tree, str)
        and TREE_RE.fullmatch(project_tree)
    ):
        raise ValueError("Quality-negative source identity is invalid")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(FILE_NAMES):
        raise ValueError("Quality-negative file index is incomplete")
    resolved: dict[str, Path] = {}
    for key, expected_name in FILE_NAMES.items():
        entry = files.get(key)
        if not isinstance(entry, dict) or set(entry) != {"name", "sha256"}:
            raise ValueError(f"Quality-negative file entry is invalid: {key}")
        if entry.get("name") != expected_name or not isinstance(
            entry.get("sha256"), str
        ) or SHA256_RE.fullmatch(entry["sha256"]) is None:
            raise ValueError(f"Quality-negative file identity is invalid: {key}")
        candidate = manifest_path.parent / expected_name
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError(f"Quality-negative file is missing: {key}")
        if file_sha256(candidate) != entry["sha256"]:
            raise ValueError(f"Quality-negative file SHA256 changed: {key}")
        resolved[key] = candidate
    derived = _validate_evidence(
        retrieval_path=resolved["retrieval"],
        quality_path=resolved["quality"],
        monitor_path=resolved["monitor"],
        server_path=resolved["server"],
        runtime_instance_path=resolved["runtime_instance"],
        expected_run_id=run_id,
        expected_commit=commit,
        expected_project_tree=project_tree,
    )
    for key, value in derived.items():
        if manifest.get(key) != value:
            raise ValueError(f"Quality-negative manifest recomputation mismatch: {key}")
    return dict(manifest)


def _copy_private(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"Evidence source is not a regular file: {source}")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with source.open("rb") as input_handle, os.fdopen(descriptor, "wb") as output_handle:
        for block in iter(lambda: input_handle.read(1024 * 1024), b""):
            output_handle.write(block)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-project-tree", required=True)
    parser.add_argument("--retrieval-file", type=Path, required=True)
    parser.add_argument("--quality-file", type=Path, required=True)
    parser.add_argument("--monitor-file", type=Path, required=True)
    parser.add_argument("--server-log", type=Path, required=True)
    parser.add_argument("--runtime-instance-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if RUN_ID_RE.fullmatch(args.run_id) is None:
        raise ValueError("Quality-negative run ID is invalid")
    if COMMIT_RE.fullmatch(args.expected_commit) is None or TREE_RE.fullmatch(
        args.expected_project_tree
    ) is None:
        raise ValueError("Quality-negative frozen source identity is invalid")
    sources = {
        "retrieval": args.retrieval_file.expanduser().resolve(),
        "quality": args.quality_file.expanduser().resolve(),
        "monitor": args.monitor_file.expanduser().resolve(),
        "server": args.server_log.expanduser().resolve(),
        "runtime_instance": args.runtime_instance_file.expanduser().resolve(),
    }
    derived = _validate_evidence(
        retrieval_path=sources["retrieval"],
        quality_path=sources["quality"],
        monitor_path=sources["monitor"],
        server_path=sources["server"],
        runtime_instance_path=sources["runtime_instance"],
        expected_run_id=args.run_id,
        expected_commit=args.expected_commit,
        expected_project_tree=args.expected_project_tree,
    )
    output = args.output_dir.expanduser().resolve()
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise FileExistsError("Quality-negative output must be a new directory")
    os.mkdir(output, 0o700)
    file_index: dict[str, dict[str, str]] = {}
    for key, name in FILE_NAMES.items():
        destination = output / name
        _copy_private(sources[key], destination)
        file_index[key] = {"name": name, "sha256": file_sha256(destination)}
    manifest = {
        "schema_version": 1,
        "evidence_type": "radeonstay-quality-negative",
        "status": "quality_rejected",
        "label": "A",
        "run_id": args.run_id,
        "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": args.expected_commit,
        "project_tree": args.expected_project_tree,
        **derived,
        "files": file_index,
    }
    manifest_path = output / "manifest.json"
    descriptor = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    load_quality_negative_bundle(manifest_path)
    print(
        json.dumps(
            {
                "status": "quality_rejected",
                "manifest": str(manifest_path),
                "manifest_sha256": file_sha256(manifest_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
