from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Any


DELIVERY_PROTOCOL = "agent_result.v1"
DELIVERY_ROOT_NAME = "deliveries"
DELIVERY_STAGING_ROOT = ".agent/delivery_staging"


@dataclass(frozen=True, slots=True)
class DeliveryCommit:
    delivery_id: str
    bundle_path: str
    artifact_refs: list[dict[str, Any]]
    manifest: dict[str, Any]


def commit_agent_result(
    *,
    parent_workspace: Path,
    child_workspace: Path,
    task_id: str,
    package_id: str,
    child_session_id: str,
    status: str,
    summary: str,
    artifacts: list[dict[str, str]],
    key_findings: list[str],
    remaining_issues: list[str],
    recommended_next_actions: list[str],
) -> DeliveryCommit:
    parent_root = _safe_workspace_root(parent_workspace, label="parent")
    child_root = _safe_workspace_root(child_workspace, label="child")
    normalized_artifacts = _normalize_artifacts(artifacts)
    source_fingerprints = [
        _artifact_source_fingerprint(child_root, artifact)
        for artifact in normalized_artifacts
    ]
    delivery_id = _delivery_id(
        task_id=task_id,
        status=status,
        summary=summary,
        artifacts=source_fingerprints,
        key_findings=key_findings,
        remaining_issues=remaining_issues,
        recommended_next_actions=recommended_next_actions,
    )
    bundle_relative = PurePosixPath(DELIVERY_ROOT_NAME, f"{task_id}-{delivery_id[:12]}")
    final_bundle = _under_root(parent_root, bundle_relative)
    manifest = {
        "protocol": DELIVERY_PROTOCOL,
        "delivery_id": delivery_id,
        "task_id": task_id,
        "package_id": package_id,
        "child_session_id": child_session_id,
        "status": status,
        "summary": summary,
        "key_findings": key_findings,
        "remaining_issues": remaining_issues,
        "recommended_next_actions": recommended_next_actions,
        "artifacts": [],
    }
    if final_bundle.exists():
        existing = _read_existing_manifest(final_bundle)
        if str(existing.get("delivery_id") or "") != delivery_id:
            raise FileExistsError(f"delivery bundle already exists with different content: {bundle_relative}")
        return DeliveryCommit(
            delivery_id=delivery_id,
            bundle_path=bundle_relative.as_posix(),
            artifact_refs=list(existing.get("artifact_refs") or []),
            manifest=existing,
        )

    staging_root = _under_root(parent_root, PurePosixPath(DELIVERY_STAGING_ROOT))
    staging_root.mkdir(parents=True, exist_ok=True)
    staging_bundle = staging_root / delivery_id
    if staging_bundle.exists():
        shutil.rmtree(staging_bundle)
    staging_bundle.mkdir(parents=True)
    artifact_refs: list[dict[str, Any]] = []
    try:
        for index, (artifact, source_fingerprint) in enumerate(
            zip(normalized_artifacts, source_fingerprints, strict=True),
            start=1,
        ):
            source_relative = PurePosixPath(artifact["path"])
            source = _under_root(child_root, source_relative)
            if not source.exists():
                raise FileNotFoundError(f"delivery artifact does not exist: {source_relative.as_posix()}")
            if source.is_symlink():
                raise ValueError(f"delivery artifact must not be a symbolic link: {source_relative.as_posix()}")
            target_name = f"{index:02d}-{source.name}"
            target = staging_bundle / target_name
            copied_files = _copy_artifact(source, target)
            copied_digest = _tree_digest(copied_files)
            if copied_digest != source_fingerprint["sha256"]:
                raise RuntimeError(f"delivery artifact changed while being copied: {source_relative.as_posix()}")
            artifact_relative = (bundle_relative / target_name).as_posix()
            manifest_item = {
                "source_path": source_relative.as_posix(),
                "path": artifact_relative,
                "description": artifact["description"],
                "kind": "directory" if source.is_dir() else "file",
                "file_count": len(copied_files),
                "size_bytes": sum(item[1] for item in copied_files),
                "sha256": copied_digest,
            }
            manifest["artifacts"].append(manifest_item)
            artifact_refs.append(
                {
                    **manifest_item,
                    "created_by": package_id,
                    "task_id": task_id,
                    "source": "agent_delivery",
                    "workspace_scope": "parent",
                }
            )
        report_relative = (bundle_relative / "delivery.json").as_posix()
        report_ref = {
            "path": report_relative,
            "description": "子 Agent 结构化交付报告",
            "kind": "json",
            "created_by": package_id,
            "task_id": task_id,
            "source": "agent_delivery_report",
            "workspace_scope": "parent",
        }
        artifact_refs.insert(0, report_ref)
        manifest["artifact_refs"] = artifact_refs
        (staging_bundle / "delivery.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        final_bundle.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_bundle, final_bundle)
    except Exception:
        shutil.rmtree(staging_bundle, ignore_errors=True)
        raise
    return DeliveryCommit(
        delivery_id=delivery_id,
        bundle_path=bundle_relative.as_posix(),
        artifact_refs=artifact_refs,
        manifest=manifest,
    )


def _normalize_artifacts(value: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    paths: set[str] = set()
    for item in value:
        path = _safe_relative_path(str(item.get("path") or ""))
        description = str(item.get("description") or "").strip()
        if not description:
            raise ValueError(f"delivery artifact description is required: {path}")
        if path in paths:
            raise ValueError(f"duplicate delivery artifact: {path}")
        paths.add(path)
        normalized.append({"path": path, "description": description})
    return normalized


def _copy_artifact(source: Path, target: Path) -> list[tuple[str, int, str]]:
    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return [(".", target.stat().st_size, _file_digest(target))]
    if not source.is_dir():
        raise ValueError(f"unsupported delivery artifact type: {source}")
    copied: list[tuple[str, int, str]] = []
    target.mkdir(parents=True)
    for child in sorted(source.rglob("*")):
        if child.is_symlink():
            raise ValueError(f"delivery directory contains a symbolic link: {child.relative_to(source)}")
        if not child.is_file():
            continue
        relative = child.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, destination)
        copied.append((relative.as_posix(), destination.stat().st_size, _file_digest(destination)))
    return copied


def _safe_workspace_root(value: Path, *, label: str) -> Path:
    root = value.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"{label} workspace does not exist: {root}")
    if root == Path(root.anchor):
        raise ValueError(f"{label} workspace must not be a filesystem root")
    return root


def _under_root(root: Path, relative: PurePosixPath) -> Path:
    candidate = root.joinpath(*relative.parts).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"delivery path escapes workspace: {relative.as_posix()}") from exc
    return candidate


def _safe_relative_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"delivery artifact path must be a safe relative path: {value}")
    return path.as_posix()


def _artifact_source_fingerprint(root: Path, artifact: dict[str, str]) -> dict[str, Any]:
    relative = PurePosixPath(artifact["path"])
    source = _under_root(root, relative)
    if not source.exists():
        raise FileNotFoundError(f"delivery artifact does not exist: {relative.as_posix()}")
    if source.is_symlink():
        raise ValueError(f"delivery artifact must not be a symbolic link: {relative.as_posix()}")
    if source.is_file():
        files = [(".", source.stat().st_size, _file_digest(source))]
        kind = "file"
    elif source.is_dir():
        files = []
        kind = "directory"
        for child in sorted(source.rglob("*")):
            if child.is_symlink():
                raise ValueError(f"delivery directory contains a symbolic link: {child.relative_to(source)}")
            if child.is_file():
                files.append((child.relative_to(source).as_posix(), child.stat().st_size, _file_digest(child)))
    else:
        raise ValueError(f"unsupported delivery artifact type: {relative.as_posix()}")
    return {
        **artifact,
        "kind": kind,
        "file_count": len(files),
        "size_bytes": sum(item[1] for item in files),
        "sha256": _tree_digest(files),
    }


def _delivery_id(
    *,
    task_id: str,
    status: str,
    summary: str,
    artifacts: list[dict[str, Any]],
    key_findings: list[str],
    remaining_issues: list[str],
    recommended_next_actions: list[str],
) -> str:
    payload = json.dumps(
        {
            "task_id": task_id,
            "status": status,
            "summary": summary,
            "artifacts": artifacts,
            "key_findings": key_findings,
            "remaining_issues": remaining_issues,
            "recommended_next_actions": recommended_next_actions,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(files: list[tuple[str, int, str]]) -> str:
    payload = json.dumps(files, ensure_ascii=False, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _read_existing_manifest(bundle: Path) -> dict[str, Any]:
    path = bundle / "delivery.json"
    if not path.is_file():
        raise ValueError(f"existing delivery bundle is incomplete: {bundle}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"existing delivery manifest is invalid: {path}")
    return value
