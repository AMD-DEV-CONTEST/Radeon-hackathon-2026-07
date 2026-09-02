#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.cleanroom_build_recipe_recovery_record import (
    make_cleanroom_build_recipe_recovery_record,
    write_cleanroom_build_recipe_recovery_record,
)
from corpus.programbench.cleanroom_image_remediation_plan_record import (
    verify_cleanroom_image_remediation_plan_record,
)
from corpus.programbench.cleanroom_image_scan_record import verify_cleanroom_image_scan_record


class BuildRecipeRecoveryStatus(str, Enum):
    BUILD_RECIPE_RECOVERY_READY = "BUILD_RECIPE_RECOVERY_READY"
    BUILD_RECIPE_RECOVERED_EXACT = "BUILD_RECIPE_RECOVERED_EXACT"
    BUILD_RECIPE_RECOVERED_PARTIAL = "BUILD_RECIPE_RECOVERED_PARTIAL"
    BUILD_RECIPE_RECONSTRUCTED_QUARANTINE_ONLY = "BUILD_RECIPE_RECONSTRUCTED_QUARANTINE_ONLY"
    BUILD_RECIPE_MISSING = "BUILD_RECIPE_MISSING"
    BUILD_RECIPE_BLOCKED_INSUFFICIENT_PROVENANCE = "BUILD_RECIPE_BLOCKED_INSUFFICIENT_PROVENANCE"
    BUILD_RECIPE_BLOCKED_NO_REMEDIATION_PLAN = "BUILD_RECIPE_BLOCKED_NO_REMEDIATION_PLAN"
    BUILD_RECIPE_BLOCKED_IMAGE_MISMATCH = "BUILD_RECIPE_BLOCKED_IMAGE_MISMATCH"
    BUILD_RECIPE_BLOCKED_DIGEST_MISMATCH = "BUILD_RECIPE_BLOCKED_DIGEST_MISMATCH"
    BUILD_RECIPE_DOCKERFILE_PRESENT = "BUILD_RECIPE_DOCKERFILE_PRESENT"
    BUILD_RECIPE_BUILD_SCRIPT_PRESENT = "BUILD_RECIPE_BUILD_SCRIPT_PRESENT"
    BUILD_RECIPE_BASE_DIGEST_PRESENT = "BUILD_RECIPE_BASE_DIGEST_PRESENT"
    BUILD_RECIPE_BASE_DIGEST_MISSING = "BUILD_RECIPE_BASE_DIGEST_MISSING"
    BUILD_RECIPE_IMAGE_HISTORY_PRESENT = "BUILD_RECIPE_IMAGE_HISTORY_PRESENT"
    BUILD_RECIPE_GO_UPDATE_COMPATIBLE = "BUILD_RECIPE_GO_UPDATE_COMPATIBLE"
    BUILD_RECIPE_MATERIAL_FIDELITY_RISK = "BUILD_RECIPE_MATERIAL_FIDELITY_RISK"
    BUILD_RECIPE_NOT_EXECUTABLE = "BUILD_RECIPE_NOT_EXECUTABLE"
    BUILD_RECIPE_TRAINING_INELIGIBLE = "BUILD_RECIPE_TRAINING_INELIGIBLE"


RECIPE_FILENAMES = {
    "dockerfile",
    "containerfile",
    "dockerfile.cleanroom",
    "dockerfile.programbench",
    "build.sh",
    "build_image.sh",
    "build-image.sh",
    "build_cleanroom.sh",
    "build-cleanroom.sh",
}


@dataclass(slots=True)
class BuildRecipeRecoveryConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_cleanroom_build_recipe_recovery")
    search_roots: list[Path] = field(default_factory=list)
    target_image: str = ""
    target_digest: str = ""
    max_files_per_root: int = 5000


class ProgramBenchCleanroomBuildRecipeRecovery:
    def __init__(self, config: BuildRecipeRecoveryConfig | None = None) -> None:
        self.config = config or BuildRecipeRecoveryConfig()

    def recover(self, remediation_plan_path: Path) -> dict[str, Any]:
        plan_path = self._resolve(remediation_plan_path)
        if not plan_path.is_file():
            return self._write_blocked(
                status=BuildRecipeRecoveryStatus.BUILD_RECIPE_BLOCKED_NO_REMEDIATION_PLAN.value,
                plan_path=plan_path,
                plan={},
                scan={},
                searched=[],
                sources=[],
                components={},
                image_metadata={},
                go_update={},
                reasons=["remediation_plan_missing"],
            )
        plan = _read_json(plan_path)
        if not verify_cleanroom_image_remediation_plan_record(plan):
            return self._write_blocked(
                status=BuildRecipeRecoveryStatus.BUILD_RECIPE_BLOCKED_NO_REMEDIATION_PLAN.value,
                plan_path=plan_path,
                plan=plan,
                scan={},
                searched=[],
                sources=[],
                components={},
                image_metadata={},
                go_update={},
                reasons=["remediation_plan_signature_invalid"],
            )

        image = str(plan.get("image_reference") or "")
        digest = str(plan.get("image_digest") or "")
        if self.config.target_image and image != self.config.target_image:
            return self._write_blocked(
                status=BuildRecipeRecoveryStatus.BUILD_RECIPE_BLOCKED_IMAGE_MISMATCH.value,
                plan_path=plan_path,
                plan=plan,
                scan={},
                searched=[],
                sources=[],
                components={},
                image_metadata={},
                go_update={},
                reasons=["target_image_mismatch"],
            )
        if self.config.target_digest and digest != self.config.target_digest:
            return self._write_blocked(
                status=BuildRecipeRecoveryStatus.BUILD_RECIPE_BLOCKED_DIGEST_MISMATCH.value,
                plan_path=plan_path,
                plan=plan,
                scan={},
                searched=[],
                sources=[],
                components={},
                image_metadata={},
                go_update={},
                reasons=["target_digest_mismatch"],
            )

        scan = self._load_scan_record(plan)
        searched, sources = self._search_sources(image)
        image_metadata = self._inspect_image_tar(scan)
        if image_metadata.get("history"):
            sources.append(
                {
                    "source_type": "image_config_history",
                    "path": str(scan.get("artifact_path") or ""),
                    "confidence": "reconstructed",
                    "execution_allowed": False,
                    "quarantine_only": True,
                    "notes": "Dockerfile-style history recovered from OCI image config; original build recipe file not recovered.",
                }
            )

        components = _classify_components(sources, image_metadata)
        go_update = _go_update_summary(plan, image_metadata, sources)
        status, statuses, reasons = _classify_status(
            components, bool(image_metadata.get("history"))
        )
        statuses = [
            BuildRecipeRecoveryStatus.BUILD_RECIPE_RECOVERY_READY.value,
            status,
            *statuses,
            BuildRecipeRecoveryStatus.BUILD_RECIPE_MATERIAL_FIDELITY_RISK.value,
            BuildRecipeRecoveryStatus.BUILD_RECIPE_NOT_EXECUTABLE.value,
            BuildRecipeRecoveryStatus.BUILD_RECIPE_TRAINING_INELIGIBLE.value,
        ]
        record = make_cleanroom_build_recipe_recovery_record(
            status=status,
            image_reference=image,
            image_digest=digest,
            remediation_plan=_rel(self.config.root, plan_path),
            searched_locations=searched,
            recovered_sources=sources,
            recipe_components=components,
            image_config_metadata=image_metadata,
            go_update=go_update,
            fidelity_assessment={
                "fidelity_class": "material_fidelity_change",
                "reason": "Updating Go runtime or base image changes the cleanroom execution environment.",
                "fidelity_preserving_rebuild": bool(
                    components.get("dockerfile_present")
                    and components.get("base_image_digest_present")
                ),
                "bounded_rerun_revalidation_required": True,
            },
            recovery_statuses=list(dict.fromkeys(statuses)),
            reasons=reasons,
            cache_ready=False,
            executable=False,
        )
        path = write_cleanroom_build_recipe_recovery_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _write_blocked(
        self,
        *,
        status: str,
        plan_path: Path,
        plan: dict[str, Any],
        scan: dict[str, Any],
        searched: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        components: dict[str, Any],
        image_metadata: dict[str, Any],
        go_update: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any]:
        record = make_cleanroom_build_recipe_recovery_record(
            status=status,
            image_reference=str(plan.get("image_reference") or self.config.target_image),
            image_digest=str(plan.get("image_digest") or self.config.target_digest),
            remediation_plan=_rel(self.config.root, plan_path),
            searched_locations=searched,
            recovered_sources=sources,
            recipe_components=components,
            image_config_metadata=image_metadata,
            go_update=go_update,
            fidelity_assessment={
                "fidelity_class": "unknown",
                "bounded_rerun_revalidation_required": True,
            },
            recovery_statuses=[
                status,
                BuildRecipeRecoveryStatus.BUILD_RECIPE_BLOCKED_INSUFFICIENT_PROVENANCE.value,
                BuildRecipeRecoveryStatus.BUILD_RECIPE_NOT_EXECUTABLE.value,
                BuildRecipeRecoveryStatus.BUILD_RECIPE_TRAINING_INELIGIBLE.value,
            ],
            reasons=reasons,
            cache_ready=False,
            executable=False,
        )
        path = write_cleanroom_build_recipe_recovery_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _load_scan_record(self, plan: dict[str, Any]) -> dict[str, Any]:
        scan_ref = str(plan.get("scan_record") or "")
        if not scan_ref:
            return {}
        scan_path = self._resolve(Path(scan_ref))
        if not scan_path.is_file():
            return {}
        scan = _read_json(scan_path)
        return scan if verify_cleanroom_image_scan_record(scan) else {}

    def _search_sources(self, image: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        searched: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        for root in self.config.search_roots:
            resolved = self._resolve(root)
            entry = {
                "path": _rel(self.config.root, resolved),
                "exists": resolved.exists(),
                "files_examined": 0,
                "matches": 0,
            }
            if not resolved.exists():
                searched.append(entry)
                continue
            files = (
                [resolved]
                if resolved.is_file()
                else sorted(p for p in resolved.rglob("*") if p.is_file())
            )
            for path in files[: self.config.max_files_per_root]:
                entry["files_examined"] += 1
                source = _classify_file(path, self.config.root)
                if source:
                    entry["matches"] += 1
                    sources.append(source)
            if len(files) > self.config.max_files_per_root:
                entry["truncated"] = True
            searched.append(entry)
        return searched, sources

    def _inspect_image_tar(self, scan: dict[str, Any]) -> dict[str, Any]:
        artifact = str(scan.get("artifact_path") or "")
        if not artifact:
            return {}
        path = Path(artifact)
        if not path.is_absolute():
            path = self._resolve(path)
        if not path.is_file():
            return {"artifact_path": str(path), "artifact_found": False}
        try:
            with tarfile.open(path, "r") as tar:
                manifest = _read_tar_json(tar, "manifest.json")
                index = _read_tar_json(tar, "index.json")
                config_path = ""
                if isinstance(manifest, list) and manifest:
                    config_path = str((manifest[0] or {}).get("Config") or "")
                config = _read_tar_json(tar, config_path) if config_path else {}
        except (tarfile.TarError, OSError, json.JSONDecodeError) as exc:
            return {"artifact_path": str(path), "artifact_found": True, "error": str(exc)}
        history = []
        if isinstance(config.get("history"), list):
            for item in config["history"]:
                if isinstance(item, dict):
                    created_by = _redact(str(item.get("created_by") or ""))
                    if created_by:
                        history.append(
                            {
                                "created": str(item.get("created") or ""),
                                "created_by": created_by,
                                "empty_layer": bool(item.get("empty_layer", False)),
                            }
                        )
        env = []
        cfg = config.get("config") if isinstance(config.get("config"), dict) else {}
        if isinstance(cfg.get("Env"), list):
            env = [str(x) for x in cfg["Env"]]
        labels = cfg.get("Labels") if isinstance(cfg.get("Labels"), dict) else {}
        return {
            "artifact_path": str(path),
            "artifact_found": True,
            "index_manifest_digest": _index_digest(index),
            "config_digest": _digest_from_config_path(config_path),
            "layer_count": len((manifest[0] or {}).get("Layers") or [])
            if isinstance(manifest, list) and manifest
            else 0,
            "history_count": len(history),
            "history": history,
            "env": env,
            "working_dir": str(cfg.get("WorkingDir") or ""),
            "labels": labels,
            "base_image_label": str(labels.get("org.opencontainers.image.version") or ""),
        }

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _classify_file(path: Path, root: Path) -> dict[str, Any] | None:
    name = path.name.lower()
    if name not in RECIPE_FILENAMES and name != "task.yaml":
        return None
    source_type = (
        "task_metadata"
        if name == "task.yaml"
        else "build_script"
        if name.endswith(".sh")
        else "dockerfile"
    )
    text = path.read_text(encoding="utf-8", errors="replace")[:20000]
    from_line = _first_match(text, r"(?im)^\s*FROM\s+(.+)$")
    go_version = _first_match(text, r"go([0-9]+\.[0-9]+(?:\.[0-9]+)?)")
    return {
        "source_type": source_type,
        "path": _rel(root, path),
        "sha256": _file_sha256(path),
        "from_line": _redact(from_line),
        "base_digest_present": "@sha256:" in from_line,
        "go_version_reference": go_version,
        "execution_allowed": False,
        "quarantine_only": source_type != "dockerfile",
    }


def _classify_components(
    sources: list[dict[str, Any]], image_metadata: dict[str, Any]
) -> dict[str, Any]:
    dockerfiles = [s for s in sources if s.get("source_type") == "dockerfile"]
    build_scripts = [s for s in sources if s.get("source_type") == "build_script"]
    metadata = [s for s in sources if s.get("source_type") == "task_metadata"]
    base_digest_present = any(bool(s.get("base_digest_present")) for s in dockerfiles)
    history_text = "\n".join(
        str(h.get("created_by") or "") for h in image_metadata.get("history") or []
    )
    return {
        "dockerfile_present": bool(dockerfiles),
        "build_script_present": bool(build_scripts),
        "task_metadata_present": bool(metadata),
        "base_image_digest_present": base_digest_present,
        "image_config_history_present": bool(image_metadata.get("history")),
        "go_runtime_version_detected": _first_match(
            history_text, r"go([0-9]+\.[0-9]+(?:\.[0-9]+)?)"
        ),
        "ubuntu_version_detected": str(image_metadata.get("base_image_label") or ""),
        "original_recipe_file_recovered": bool(dockerfiles),
        "reconstructed_from_image_history": bool(image_metadata.get("history")),
    }


def _go_update_summary(
    plan: dict[str, Any], image_metadata: dict[str, Any], sources: list[dict[str, Any]]
) -> dict[str, Any]:
    target = str((plan.get("required_inputs") or {}).get("go_version_target") or "1.24.13")
    history_text = "\n".join(
        str(h.get("created_by") or "") for h in image_metadata.get("history") or []
    )
    env_text = "\n".join(str(item) for item in image_metadata.get("env") or [])
    source_text = "\n".join(str(s.get("go_version_reference") or "") for s in sources)
    detected = _first_match(history_text + "\n" + source_text, r"go([0-9]+\.[0-9]+(?:\.[0-9]+)?)")
    compatible = bool(
        detected
        and "dl.google.com/go/go" in history_text
        and "/usr/local/go" in (history_text + "\n" + env_text)
    )
    return {
        "current_version_detected": detected,
        "target_version": target,
        "update_strategy": "replace_go_tarball_url_and_verify_version" if compatible else "unknown",
        "recipe_compatible": compatible,
        "requires_rebuild": True,
        "requires_rescan": True,
        "requires_hydration_policy_rerun": True,
        "requires_bounded_rerun_revalidation": True,
    }


def _classify_status(
    components: dict[str, Any], has_history: bool
) -> tuple[str, list[str], list[str]]:
    statuses: list[str] = []
    reasons: list[str] = []
    if components.get("dockerfile_present"):
        statuses.append(BuildRecipeRecoveryStatus.BUILD_RECIPE_DOCKERFILE_PRESENT.value)
    if components.get("build_script_present"):
        statuses.append(BuildRecipeRecoveryStatus.BUILD_RECIPE_BUILD_SCRIPT_PRESENT.value)
    if components.get("base_image_digest_present"):
        statuses.append(BuildRecipeRecoveryStatus.BUILD_RECIPE_BASE_DIGEST_PRESENT.value)
    else:
        statuses.append(BuildRecipeRecoveryStatus.BUILD_RECIPE_BASE_DIGEST_MISSING.value)
        reasons.append("base_image_digest_not_recovered")
    if has_history:
        statuses.append(BuildRecipeRecoveryStatus.BUILD_RECIPE_IMAGE_HISTORY_PRESENT.value)
    if components.get("go_runtime_version_detected"):
        statuses.append(BuildRecipeRecoveryStatus.BUILD_RECIPE_GO_UPDATE_COMPATIBLE.value)

    if components.get("dockerfile_present") and components.get("base_image_digest_present"):
        return BuildRecipeRecoveryStatus.BUILD_RECIPE_RECOVERED_EXACT.value, statuses, reasons
    if components.get("dockerfile_present") or components.get("build_script_present"):
        reasons.append("recipe_present_but_not_enough_base_provenance")
        return BuildRecipeRecoveryStatus.BUILD_RECIPE_RECOVERED_PARTIAL.value, statuses, reasons
    if has_history:
        statuses.append(
            BuildRecipeRecoveryStatus.BUILD_RECIPE_BLOCKED_INSUFFICIENT_PROVENANCE.value
        )
        reasons.append("image_history_reconstructs_steps_but_original_recipe_file_missing")
        return (
            BuildRecipeRecoveryStatus.BUILD_RECIPE_RECONSTRUCTED_QUARANTINE_ONLY.value,
            statuses,
            reasons,
        )
    statuses.append(BuildRecipeRecoveryStatus.BUILD_RECIPE_BLOCKED_INSUFFICIENT_PROVENANCE.value)
    reasons.append("no_build_recipe_or_image_history_recovered")
    return BuildRecipeRecoveryStatus.BUILD_RECIPE_MISSING.value, statuses, reasons


def _read_tar_json(tar: tarfile.TarFile, member_name: str) -> Any:
    if not member_name:
        return {}
    member = tar.getmember(member_name)
    fileobj = tar.extractfile(member)
    if fileobj is None:
        return {}
    return json.loads(fileobj.read().decode("utf-8", errors="replace"))


def _index_digest(index: Any) -> str:
    if isinstance(index, dict):
        manifests = index.get("manifests")
        if isinstance(manifests, list) and manifests:
            return str((manifests[0] or {}).get("digest") or "")
    return ""


def _digest_from_config_path(config_path: str) -> str:
    marker = "blobs/sha256/"
    return f"sha256:{config_path.split(marker, 1)[1]}" if marker in config_path else ""


def _redact(value: str) -> str:
    value = re.sub(
        r"https://x-access-token:[^/@\s]+@", "https://x-access-token:ghp_<redacted>@", value
    )
    value = re.sub(r"https://[^/@\s]+:[^/@\s]+@", "https://<redacted>@", value)
    value = re.sub(r"ghp_[A-Za-z0-9_]+", "ghp_<redacted>", value)
    return value


def _file_sha256(path: Path) -> str:
    h = __import__("hashlib").sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return data if isinstance(data, dict) else {}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover ProgramBench cleanroom image build recipe evidence."
    )
    parser.add_argument("remediation_plan", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_cleanroom_build_recipe_recovery"),
    )
    parser.add_argument("--search-root", action="append", type=Path, default=[])
    parser.add_argument("--target-image", default="")
    parser.add_argument("--target-digest", default="")
    args = parser.parse_args()
    result = ProgramBenchCleanroomBuildRecipeRecovery(
        BuildRecipeRecoveryConfig(
            root=args.root,
            output_dir=args.output_dir,
            search_roots=args.search_root,
            target_image=args.target_image,
            target_digest=args.target_digest,
        )
    ).recover(args.remediation_plan)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
