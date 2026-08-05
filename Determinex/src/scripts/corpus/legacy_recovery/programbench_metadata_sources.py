from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

METADATA_FILENAMES = ("manifest.json", "task.json", "metadata.json", "programbench.json")
LOCAL_VERIFIER_FILENAMES = ("local_verifier.json", "replay_verifier.json")


@dataclass(slots=True)
class MetadataEvidence:
    task_images: dict[str, str] = field(default_factory=dict)
    local_verifiers: dict[str, dict[str, Any]] = field(default_factory=dict)
    dockerfiles: list[str] = field(default_factory=list)
    executables: list[str] = field(default_factory=list)
    build_files: list[str] = field(default_factory=list)
    module_files: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


def collect_metadata_evidence(candidate: dict[str, Any], root: Path) -> MetadataEvidence:
    evidence = MetadataEvidence()
    _collect_inline(candidate, evidence)
    if not root or not root.exists():
        return evidence
    _collect_metadata_files(root, evidence)
    _collect_local_verifier_files(root, evidence)
    _collect_project_shape(root, evidence)
    return evidence


def _collect_inline(candidate: dict[str, Any], evidence: MetadataEvidence) -> None:
    for key in ("task_image", "docker_image", "image"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            evidence.task_images[f"candidate.{key}"] = value.strip()
    inline = candidate.get("local_verifier")
    if isinstance(inline, dict):
        evidence.local_verifiers["candidate.local_verifier"] = inline
    for key in ("tool", "legacy_row_hash", "language_guess", "expected_verifier"):
        if candidate.get(key):
            evidence.provenance[key] = candidate[key]


def _collect_metadata_files(root: Path, evidence: MetadataEvidence) -> None:
    for name in METADATA_FILENAMES:
        path = root / name
        if not path.is_file():
            continue
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        for key in ("task_image", "docker_image", "image"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                evidence.task_images[str(path)] = value.strip()
        for key in ("tool", "task_id", "programbench_task_id", "source_repo", "source_commit"):
            if data.get(key):
                evidence.provenance[key] = data[key]


def _collect_local_verifier_files(root: Path, evidence: MetadataEvidence) -> None:
    for name in LOCAL_VERIFIER_FILENAMES:
        path = root / name
        if not path.is_file():
            continue
        data = _read_json(path)
        if isinstance(data, dict):
            evidence.local_verifiers[str(path)] = data


def _collect_project_shape(root: Path, evidence: MetadataEvidence) -> None:
    for path in root.rglob("*"):
        rel = str(path.relative_to(root)).replace("\\", "/")
        if path.is_dir() and rel in {".git", "target", "node_modules", ".venv", "venv"}:
            continue
        if path.is_file():
            lower = path.name.lower()
            if lower in {"dockerfile", "containerfile"} or lower.startswith("dockerfile."):
                evidence.dockerfiles.append(rel)
            elif lower in {
                "compile.sh",
                "build.sh",
                "makefile",
                "cmakelists.txt",
                "go.mod",
                "cargo.toml",
                "package.json",
            }:
                evidence.build_files.append(rel)
                if lower in {"go.mod", "cargo.toml", "package.json"}:
                    evidence.module_files.append(rel)
            elif path.parent == root and "." not in path.name and path.stat().st_size > 0:
                evidence.executables.append(rel)
        if len(evidence.dockerfiles) > 10 and len(evidence.build_files) > 20:
            break


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None
