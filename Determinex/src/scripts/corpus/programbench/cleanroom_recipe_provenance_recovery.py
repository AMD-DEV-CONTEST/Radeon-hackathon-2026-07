#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.cleanroom_build_recipe_provenance_gap_record import (
    verify_cleanroom_build_recipe_provenance_gap_record,
)
from corpus.programbench.cleanroom_build_recipe_recovery_record import (
    verify_cleanroom_build_recipe_recovery_record,
)
from corpus.programbench.cleanroom_image_remediation_plan_record import (
    verify_cleanroom_image_remediation_plan_record,
)
from corpus.programbench.cleanroom_recipe_provenance_recovery_record import (
    make_cleanroom_recipe_provenance_recovery_record,
    write_cleanroom_recipe_provenance_recovery_record,
)


class RecipeProvenanceRecoveryStatus(str, Enum):
    RECIPE_PROVENANCE_RECOVERY_READY = "RECIPE_PROVENANCE_RECOVERY_READY"
    RECIPE_PROVENANCE_RECOVERED_EXACT = "RECIPE_PROVENANCE_RECOVERED_EXACT"
    RECIPE_PROVENANCE_RECOVERED_PARTIAL = "RECIPE_PROVENANCE_RECOVERED_PARTIAL"
    BASE_IMAGE_PROVENANCE_RECOVERED_EXACT = "BASE_IMAGE_PROVENANCE_RECOVERED_EXACT"
    BASE_IMAGE_PROVENANCE_RECOVERED_PARTIAL = "BASE_IMAGE_PROVENANCE_RECOVERED_PARTIAL"
    PROVENANCE_RECOVERY_BLOCKED = "PROVENANCE_RECOVERY_BLOCKED"
    PROVENANCE_RECOVERY_EXHAUSTED = "PROVENANCE_RECOVERY_EXHAUSTED"
    REBUILD_PROVENANCE_READY = "REBUILD_PROVENANCE_READY"
    REBUILD_PROVENANCE_PARTIAL_QUARANTINE_ONLY = "REBUILD_PROVENANCE_PARTIAL_QUARANTINE_ONLY"
    REBUILD_PROVENANCE_BLOCKED = "REBUILD_PROVENANCE_BLOCKED"
    RECIPE_PROVENANCE_BLOCKED_NO_GAP = "RECIPE_PROVENANCE_BLOCKED_NO_GAP"
    RECIPE_PROVENANCE_BLOCKED_IMAGE_MISMATCH = "RECIPE_PROVENANCE_BLOCKED_IMAGE_MISMATCH"
    RECIPE_PROVENANCE_BLOCKED_DIGEST_MISMATCH = "RECIPE_PROVENANCE_BLOCKED_DIGEST_MISMATCH"
    ORIGINAL_RECIPE_STILL_MISSING = "ORIGINAL_RECIPE_STILL_MISSING"
    BASE_IMAGE_DIGEST_STILL_MISSING = "BASE_IMAGE_DIGEST_STILL_MISSING"
    OCI_HISTORY_REMAINS_QUARANTINE_ONLY = "OCI_HISTORY_REMAINS_QUARANTINE_ONLY"
    MATERIAL_FIDELITY_RISK_REMAINS = "MATERIAL_FIDELITY_RISK_REMAINS"
    REBUILD_NOT_AUTHORIZED = "REBUILD_NOT_AUTHORIZED"
    DOCKER_PULL_NOT_AUTHORIZED = "DOCKER_PULL_NOT_AUTHORIZED"
    DOCKER_EXECUTION_NOT_AUTHORIZED = "DOCKER_EXECUTION_NOT_AUTHORIZED"
    HYDRATION_NOT_AUTHORIZED = "HYDRATION_NOT_AUTHORIZED"
    PROGRAMBENCH_RERUN_NOT_AUTHORIZED = "PROGRAMBENCH_RERUN_NOT_AUTHORIZED"
    CACHE_READY_FALSE = "CACHE_READY_FALSE"
    TRAINING_INELIGIBLE = "TRAINING_INELIGIBLE"


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
class RecipeProvenanceRecoveryConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_cleanroom_recipe_provenance_recovery")
    search_roots: list[Path] = field(default_factory=list)
    target_image: str = ""
    target_digest: str = ""
    max_files_per_root: int = 5000


class ProgramBenchCleanroomRecipeProvenanceRecovery:
    def __init__(self, config: RecipeProvenanceRecoveryConfig | None = None) -> None:
        self.config = config or RecipeProvenanceRecoveryConfig()

    def recover(self, gap_path: Path) -> dict[str, Any]:
        resolved_gap = self._resolve(gap_path)
        gap = _read_json(resolved_gap) if resolved_gap.is_file() else {}
        if not resolved_gap.is_file() or not verify_cleanroom_build_recipe_provenance_gap_record(
            gap
        ):
            return self._write_record(
                status=RecipeProvenanceRecoveryStatus.PROVENANCE_RECOVERY_BLOCKED.value,
                decision=RecipeProvenanceRecoveryStatus.REBUILD_PROVENANCE_BLOCKED.value,
                image_reference=self.config.target_image,
                image_digest=self.config.target_digest,
                provenance_gap=_rel(self.config.root, resolved_gap),
                remediation_plan="",
                recipe_recovery="",
                searched_locations=[],
                recovered=[],
                statuses=[
                    RecipeProvenanceRecoveryStatus.RECIPE_PROVENANCE_BLOCKED_NO_GAP.value,
                    *_blocked_statuses(),
                ],
                gap_closure=_gap_closure(False, False, False),
                reasons=["provenance_gap_missing_or_invalid"],
            )

        image = str(gap.get("image_reference") or "")
        digest = str(gap.get("image_digest") or "")
        if self.config.target_image and image != self.config.target_image:
            return self._blocked_mismatch(
                gap,
                resolved_gap,
                RecipeProvenanceRecoveryStatus.RECIPE_PROVENANCE_BLOCKED_IMAGE_MISMATCH.value,
                ["image_reference_mismatch"],
            )
        if self.config.target_digest and digest != self.config.target_digest:
            return self._blocked_mismatch(
                gap,
                resolved_gap,
                RecipeProvenanceRecoveryStatus.RECIPE_PROVENANCE_BLOCKED_DIGEST_MISMATCH.value,
                ["image_digest_mismatch"],
            )

        plan_ref = str(gap.get("remediation_plan") or "")
        recovery_ref = str(gap.get("recipe_recovery") or "")
        plan = _read_json(self._resolve(Path(plan_ref))) if plan_ref else {}
        recovery = _read_json(self._resolve(Path(recovery_ref))) if recovery_ref else {}
        if not verify_cleanroom_image_remediation_plan_record(
            plan
        ) or not verify_cleanroom_build_recipe_recovery_record(recovery):
            return self._write_record(
                status=RecipeProvenanceRecoveryStatus.PROVENANCE_RECOVERY_BLOCKED.value,
                decision=RecipeProvenanceRecoveryStatus.REBUILD_PROVENANCE_BLOCKED.value,
                image_reference=image,
                image_digest=digest,
                provenance_gap=_rel(self.config.root, resolved_gap),
                remediation_plan=plan_ref,
                recipe_recovery=recovery_ref,
                searched_locations=[],
                recovered=[],
                statuses=[
                    RecipeProvenanceRecoveryStatus.PROVENANCE_RECOVERY_BLOCKED.value,
                    *_blocked_statuses(),
                ],
                gap_closure=_gap_closure(False, False, False),
                reasons=["gap_referenced_plan_or_recovery_invalid"],
            )

        searched, recovered = self._search_allowed_sources(image, digest)
        original_exact = _has_exact_recipe(recovered)
        original_partial = _has_partial_recipe(recovered)
        base_exact = _has_exact_base_digest(recovered)
        base_partial = _has_partial_base(recovered)
        go_compatible = _go_update_compatible(plan, recovery, recovered)
        material_risk = _material_fidelity_risk(gap, recovery)
        status, decision, statuses, reasons = _classify(
            original_exact=original_exact,
            original_partial=original_partial,
            base_exact=base_exact,
            base_partial=base_partial,
            go_compatible=go_compatible,
            material_risk=material_risk,
        )
        statuses = [
            RecipeProvenanceRecoveryStatus.RECIPE_PROVENANCE_RECOVERY_READY.value,
            status,
            decision,
            *statuses,
            *_blocked_statuses(),
        ]
        record = make_cleanroom_recipe_provenance_recovery_record(
            status=status,
            decision=decision,
            image_reference=image,
            image_digest=digest,
            provenance_gap=_rel(self.config.root, resolved_gap),
            remediation_plan=plan_ref,
            recipe_recovery=recovery_ref,
            searched_locations=searched,
            recovered_provenance=recovered,
            provenance_statuses=list(dict.fromkeys(statuses)),
            gap_closure=_gap_closure(original_exact, base_exact, go_compatible),
            go_remediation={
                "current_version": str(
                    (recovery.get("go_update") or {}).get("current_version_detected") or ""
                ),
                "target_version": str(
                    (recovery.get("go_update") or {}).get("target_version") or "1.24.13"
                ),
                "compatible_with_recovered_recipe": bool(go_compatible),
                "requires_rebuild": True,
                "requires_rescan": True,
                "requires_hydration_policy_rerun": True,
                "requires_bounded_rerun_revalidation": True,
            },
            fidelity_assessment={
                "fidelity_risk": "material" if material_risk else "unknown",
                "fidelity_preserving_rebuild": bool(
                    original_exact and base_exact and not material_risk
                ),
                "material_change_requires_review": bool(material_risk),
            },
            authorization=_authorization(rebuild_ready=original_exact and base_exact),
            reasons=reasons,
            cache_ready=False,
            executable=False,
        )
        path = write_cleanroom_recipe_provenance_recovery_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _blocked_mismatch(
        self,
        gap: dict[str, Any],
        gap_path: Path,
        status: str,
        reasons: list[str],
    ) -> dict[str, Any]:
        return self._write_record(
            status=RecipeProvenanceRecoveryStatus.PROVENANCE_RECOVERY_BLOCKED.value,
            decision=RecipeProvenanceRecoveryStatus.REBUILD_PROVENANCE_BLOCKED.value,
            image_reference=str(gap.get("image_reference") or self.config.target_image),
            image_digest=str(gap.get("image_digest") or self.config.target_digest),
            provenance_gap=_rel(self.config.root, gap_path),
            remediation_plan=str(gap.get("remediation_plan") or ""),
            recipe_recovery=str(gap.get("recipe_recovery") or ""),
            searched_locations=[],
            recovered=[],
            statuses=[status, *_blocked_statuses()],
            gap_closure=_gap_closure(False, False, False),
            reasons=reasons,
        )

    def _write_record(
        self,
        *,
        status: str,
        decision: str,
        image_reference: str,
        image_digest: str,
        provenance_gap: str,
        remediation_plan: str,
        recipe_recovery: str,
        searched_locations: list[dict[str, Any]],
        recovered: list[dict[str, Any]],
        statuses: list[str],
        gap_closure: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any]:
        record = make_cleanroom_recipe_provenance_recovery_record(
            status=status,
            decision=decision,
            image_reference=image_reference,
            image_digest=image_digest,
            provenance_gap=provenance_gap,
            remediation_plan=remediation_plan,
            recipe_recovery=recipe_recovery,
            searched_locations=searched_locations,
            recovered_provenance=recovered,
            provenance_statuses=list(dict.fromkeys(statuses)),
            gap_closure=gap_closure,
            authorization=_authorization(rebuild_ready=False),
            reasons=reasons,
            cache_ready=False,
            executable=False,
        )
        path = write_cleanroom_recipe_provenance_recovery_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _search_allowed_sources(
        self, image: str, digest: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        roots = self.config.search_roots or _default_search_roots()
        searched: list[dict[str, Any]] = []
        recovered: list[dict[str, Any]] = []
        for root in roots:
            resolved = self._resolve(root)
            entry = {
                "path": _rel(self.config.root, resolved),
                "exists": resolved.exists(),
                "files_examined": 0,
                "matches": 0,
                "source_policy": "local_or_admitted_only",
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
                for item in _classify_provenance_file(path, self.config.root, image, digest):
                    entry["matches"] += 1
                    recovered.append(item)
            if len(files) > self.config.max_files_per_root:
                entry["truncated"] = True
            searched.append(entry)
        return searched, recovered

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _classify_provenance_file(
    path: Path, root: Path, image: str, digest: str
) -> list[dict[str, Any]]:
    name = path.name.lower()
    if name in RECIPE_FILENAMES:
        return [_recipe_file_source(path, root)]
    if path.suffix.lower() != ".json" and name != "task.yaml":
        return []
    text = path.read_text(encoding="utf-8", errors="replace")[:100000]
    items: list[dict[str, Any]] = []
    if name == "task.yaml":
        if "repository:" in text and "commit:" in text:
            items.append(
                {
                    "source_type": "task_metadata",
                    "path": _rel(root, path),
                    "provenance_level": "partial",
                    "original_recipe": False,
                    "base_image_digest": "",
                    "execution_allowed": False,
                    "quarantine_only": True,
                    "notes": "Task metadata proves source repository/commit, not cleanroom build recipe or base image digest.",
                }
            )
        return items
    data = _read_json(path)
    if not data:
        return items
    data_image = str(data.get("image_reference") or data.get("image") or "")
    data_digest = str(
        data.get("image_digest") or data.get("manifest_digest") or data.get("digest") or ""
    )
    if data_image and data_image != image:
        return items
    if data_digest and data_digest not in {digest, ""}:
        return items
    if not data_image and not data_digest and image not in text and digest not in text:
        return items
    if _contains_exact_recipe_provenance(data):
        items.append(
            {
                "source_type": "operator_or_internal_recipe_provenance",
                "path": _rel(root, path),
                "provenance_level": "exact",
                "original_recipe": True,
                "base_image_digest": _first_digest_value(data),
                "execution_allowed": False,
                "quarantine_only": False,
                "notes": "Structured provenance record supplies original recipe and pinned base image digest.",
            }
        )
    elif _contains_partial_recipe_hint(data):
        items.append(
            {
                "source_type": "signed_provenance_hint",
                "path": _rel(root, path),
                "provenance_level": "partial",
                "original_recipe": False,
                "base_image_digest": _first_digest_value(data),
                "execution_allowed": False,
                "quarantine_only": True,
                "notes": "Signed local evidence references image provenance but does not supply complete rebuild authority.",
            }
        )
    return items


def _recipe_file_source(path: Path, root: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")[:100000]
    from_line = _first_match(text, r"(?im)^\s*FROM\s+(.+)$")
    base_digest = _first_match(from_line, r"(@sha256:[0-9a-fA-F]{32,128})")
    go_version = _first_match(text, r"go([0-9]+\.[0-9]+(?:\.[0-9]+)?)")
    return {
        "source_type": "original_recipe_file_candidate",
        "path": _rel(root, path),
        "sha256": _file_sha256(path),
        "provenance_level": "exact" if base_digest else "partial",
        "original_recipe": True,
        "from_line": _redact(from_line),
        "base_image_digest": base_digest[1:] if base_digest.startswith("@") else base_digest,
        "go_version_reference": go_version,
        "execution_allowed": False,
        "quarantine_only": not bool(base_digest),
        "notes": "Local recipe-like file found; exact rebuild provenance requires digest-pinned FROM.",
    }


def _contains_exact_recipe_provenance(data: dict[str, Any]) -> bool:
    flat = _flatten(data)
    has_recipe = any(
        k.endswith("original_cleanroom_build_recipe") or k.endswith("recipe_path") for k in flat
    )
    has_digest = bool(_first_digest_value(data))
    return has_recipe and has_digest


def _contains_partial_recipe_hint(data: dict[str, Any]) -> bool:
    flat = _flatten(data)
    keys = " ".join(flat.keys()).lower()
    values = " ".join(str(v).lower() for v in flat.values())
    return any(
        token in keys + " " + values
        for token in ("provenance", "recipe", "dockerfile", "base_image", "manifest_digest")
    )


def _flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten(value, child))
    elif isinstance(data, list):
        for idx, value in enumerate(data):
            out.update(_flatten(value, f"{prefix}.{idx}"))
    else:
        out[prefix] = data
    return out


def _first_digest_value(data: dict[str, Any]) -> str:
    for key, value in _flatten(data).items():
        if "base" in key.lower() and "digest" in key.lower():
            match = re.search(r"sha256:[0-9a-fA-F]{32,128}", str(value))
            if match:
                return match.group(0)
    return ""


def _has_exact_recipe(recovered: list[dict[str, Any]]) -> bool:
    return any(
        bool(item.get("original_recipe")) and item.get("provenance_level") == "exact"
        for item in recovered
    )


def _has_partial_recipe(recovered: list[dict[str, Any]]) -> bool:
    return any(
        bool(item.get("original_recipe"))
        or item.get("source_type") in {"task_metadata", "signed_provenance_hint"}
        for item in recovered
    )


def _has_exact_base_digest(recovered: list[dict[str, Any]]) -> bool:
    return any(
        bool(item.get("base_image_digest")) and item.get("provenance_level") == "exact"
        for item in recovered
    )


def _has_partial_base(recovered: list[dict[str, Any]]) -> bool:
    return any(bool(item.get("base_image_digest")) for item in recovered)


def _go_update_compatible(
    plan: dict[str, Any], recovery: dict[str, Any], recovered: list[dict[str, Any]]
) -> bool:
    current = str((recovery.get("go_update") or {}).get("current_version_detected") or "")
    target = str((recovery.get("go_update") or {}).get("target_version") or "")
    if current and target and bool((recovery.get("go_update") or {}).get("recipe_compatible")):
        return True
    return any(str(item.get("go_version_reference") or "") for item in recovered) and bool(plan)


def _material_fidelity_risk(gap: dict[str, Any], recovery: dict[str, Any]) -> bool:
    statuses = set(gap.get("gap_statuses") or [])
    fidelity = (
        recovery.get("fidelity_assessment")
        if isinstance(recovery.get("fidelity_assessment"), dict)
        else {}
    )
    return (
        "MATERIAL_FIDELITY_RISK" in statuses
        or str(fidelity.get("fidelity_class") or "") == "material_fidelity_change"
    )


def _classify(
    *,
    original_exact: bool,
    original_partial: bool,
    base_exact: bool,
    base_partial: bool,
    go_compatible: bool,
    material_risk: bool,
) -> tuple[str, str, list[str], list[str]]:
    statuses: list[str] = []
    reasons: list[str] = []
    if original_exact:
        statuses.append(RecipeProvenanceRecoveryStatus.RECIPE_PROVENANCE_RECOVERED_EXACT.value)
    elif original_partial:
        statuses.append(RecipeProvenanceRecoveryStatus.RECIPE_PROVENANCE_RECOVERED_PARTIAL.value)
        reasons.append("original_recipe_provenance_partial_only")
    else:
        statuses.append(RecipeProvenanceRecoveryStatus.ORIGINAL_RECIPE_STILL_MISSING.value)
        reasons.append("original_recipe_not_recovered")

    if base_exact:
        statuses.append(RecipeProvenanceRecoveryStatus.BASE_IMAGE_PROVENANCE_RECOVERED_EXACT.value)
    elif base_partial:
        statuses.append(
            RecipeProvenanceRecoveryStatus.BASE_IMAGE_PROVENANCE_RECOVERED_PARTIAL.value
        )
        reasons.append("base_image_provenance_partial_only")
    else:
        statuses.append(RecipeProvenanceRecoveryStatus.BASE_IMAGE_DIGEST_STILL_MISSING.value)
        reasons.append("base_image_digest_not_recovered")

    if material_risk:
        statuses.append(RecipeProvenanceRecoveryStatus.MATERIAL_FIDELITY_RISK_REMAINS.value)
        reasons.append("go_or_base_change_has_material_fidelity_risk")
    if not original_exact or not base_exact:
        statuses.append(RecipeProvenanceRecoveryStatus.OCI_HISTORY_REMAINS_QUARANTINE_ONLY.value)

    if original_exact and base_exact and go_compatible:
        return (
            RecipeProvenanceRecoveryStatus.RECIPE_PROVENANCE_RECOVERED_EXACT.value,
            RecipeProvenanceRecoveryStatus.REBUILD_PROVENANCE_READY.value,
            statuses,
            reasons,
        )
    if original_partial or base_partial:
        return (
            RecipeProvenanceRecoveryStatus.RECIPE_PROVENANCE_RECOVERED_PARTIAL.value,
            RecipeProvenanceRecoveryStatus.REBUILD_PROVENANCE_PARTIAL_QUARANTINE_ONLY.value,
            statuses,
            reasons,
        )
    return (
        RecipeProvenanceRecoveryStatus.PROVENANCE_RECOVERY_EXHAUSTED.value,
        RecipeProvenanceRecoveryStatus.REBUILD_PROVENANCE_BLOCKED.value,
        statuses,
        reasons,
    )


def _gap_closure(original_exact: bool, base_exact: bool, go_compatible: bool) -> dict[str, Any]:
    return {
        "original_cleanroom_build_recipe_closed": bool(original_exact),
        "pinned_base_image_digest_closed": bool(base_exact),
        "non_history_recipe_source_closed": bool(original_exact),
        "go_runtime_update_plan_available": bool(go_compatible),
        "all_required_provenance_closed": bool(original_exact and base_exact and go_compatible),
    }


def _authorization(*, rebuild_ready: bool) -> dict[str, bool]:
    return {
        "rebuild_authorized": bool(rebuild_ready),
        "docker_pull_authorized": False,
        "docker_execution_authorized": False,
        "hydration_authorized": False,
        "programbench_rerun_authorized": False,
        "policy_exception_authorized": False,
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
    }


def _blocked_statuses() -> list[str]:
    return [
        RecipeProvenanceRecoveryStatus.REBUILD_NOT_AUTHORIZED.value,
        RecipeProvenanceRecoveryStatus.DOCKER_PULL_NOT_AUTHORIZED.value,
        RecipeProvenanceRecoveryStatus.DOCKER_EXECUTION_NOT_AUTHORIZED.value,
        RecipeProvenanceRecoveryStatus.HYDRATION_NOT_AUTHORIZED.value,
        RecipeProvenanceRecoveryStatus.PROGRAMBENCH_RERUN_NOT_AUTHORIZED.value,
        RecipeProvenanceRecoveryStatus.CACHE_READY_FALSE.value,
        RecipeProvenanceRecoveryStatus.TRAINING_INELIGIBLE.value,
    ]


def _default_search_roots() -> list[Path]:
    return [
        Path("T:/Dev/ProgramBench/src/programbench/data/tasks/doxygen__doxygen.966d98e"),
        Path("assurance/evidence/programbench_cleanroom_build_recipe_recovery"),
        Path("assurance/evidence/programbench_cleanroom_build_recipe_provenance_gaps"),
        Path("assurance/evidence/programbench_dockerhub_manifest_provenance"),
        Path("assurance/evidence/programbench_operator_artifact_admissions"),
        Path("locks/sentinel"),
    ]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _file_sha256(path: Path) -> str:
    h = __import__("hashlib").sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _redact(value: str) -> str:
    value = re.sub(
        r"https://x-access-token:[^/@\s]+@", "https://x-access-token:ghp_<redacted>@", value
    )
    value = re.sub(r"https://[^/@\s]+:[^/@\s]+@", "https://<redacted>@", value)
    value = re.sub(r"ghp_[A-Za-z0-9_]+", "ghp_<redacted>", value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover missing ProgramBench cleanroom recipe provenance."
    )
    parser.add_argument("provenance_gap", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_cleanroom_recipe_provenance_recovery"),
    )
    parser.add_argument("--search-root", action="append", type=Path, default=[])
    parser.add_argument("--target-image", default="")
    parser.add_argument("--target-digest", default="")
    args = parser.parse_args()
    result = ProgramBenchCleanroomRecipeProvenanceRecovery(
        RecipeProvenanceRecoveryConfig(
            root=args.root,
            output_dir=args.output_dir,
            search_roots=args.search_root,
            target_image=args.target_image,
            target_digest=args.target_digest,
        )
    ).recover(args.provenance_gap)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
