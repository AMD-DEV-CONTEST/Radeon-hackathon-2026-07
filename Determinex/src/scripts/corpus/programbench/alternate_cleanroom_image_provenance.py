#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.alternate_cleanroom_image_provenance_record import (
    make_alternate_cleanroom_image_provenance_record,
    write_alternate_cleanroom_image_provenance_record,
)
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
    verify_cleanroom_recipe_provenance_recovery_record,
)
from corpus.programbench.operator_provenance_request_packet_record import (
    verify_operator_provenance_request_packet_record,
)
from corpus.programbench.rebuild_provenance_quarantine_decision_record import (
    verify_rebuild_provenance_quarantine_decision_record,
)


class AlternateCleanroomImageProvenanceStatus(str, Enum):
    ALTERNATE_CLEANROOM_PROVENANCE_FOUND_EXACT = "ALTERNATE_CLEANROOM_PROVENANCE_FOUND_EXACT"
    ALTERNATE_CLEANROOM_PROVENANCE_FOUND_PARTIAL = "ALTERNATE_CLEANROOM_PROVENANCE_FOUND_PARTIAL"
    ALTERNATE_CLEANROOM_PROVENANCE_NOT_FOUND = "ALTERNATE_CLEANROOM_PROVENANCE_NOT_FOUND"
    ALTERNATE_CLEANROOM_PROVENANCE_BLOCKED = "ALTERNATE_CLEANROOM_PROVENANCE_BLOCKED"
    ALTERNATE_CLEANROOM_FIDELITY_CHANGE_REQUIRED = "ALTERNATE_CLEANROOM_FIDELITY_CHANGE_REQUIRED"
    ALTERNATE_IMAGE_CANDIDATE_ADMISSIBLE = "ALTERNATE_IMAGE_CANDIDATE_ADMISSIBLE"
    ALTERNATE_IMAGE_CANDIDATE_QUARANTINE_ONLY = "ALTERNATE_IMAGE_CANDIDATE_QUARANTINE_ONLY"
    ALTERNATE_IMAGE_CANDIDATE_BLOCKED = "ALTERNATE_IMAGE_CANDIDATE_BLOCKED"
    NO_ALTERNATE_IMAGE_CANDIDATE_FOUND = "NO_ALTERNATE_IMAGE_CANDIDATE_FOUND"
    ALTERNATE_IMAGE_BLOCKED_NO_REQUEST = "ALTERNATE_IMAGE_BLOCKED_NO_REQUEST"
    ALTERNATE_IMAGE_BLOCKED_IMAGE_MISMATCH = "ALTERNATE_IMAGE_BLOCKED_IMAGE_MISMATCH"
    ALTERNATE_IMAGE_BLOCKED_DIGEST_MISMATCH = "ALTERNATE_IMAGE_BLOCKED_DIGEST_MISMATCH"
    ALTERNATE_IMAGE_BLOCKED_CHAIN_INVALID = "ALTERNATE_IMAGE_BLOCKED_CHAIN_INVALID"
    LATEST_TAG_REJECTED = "LATEST_TAG_REJECTED"
    NAME_ONLY_IMAGE_REJECTED = "NAME_ONLY_IMAGE_REJECTED"
    INFERRED_OFFICIALNESS_REJECTED = "INFERRED_OFFICIALNESS_REJECTED"
    DOCKER_PULL_NOT_AUTHORIZED = "DOCKER_PULL_NOT_AUTHORIZED"
    DOCKER_EXECUTION_NOT_AUTHORIZED = "DOCKER_EXECUTION_NOT_AUTHORIZED"
    HYDRATION_NOT_AUTHORIZED = "HYDRATION_NOT_AUTHORIZED"
    PROGRAMBENCH_RERUN_NOT_AUTHORIZED = "PROGRAMBENCH_RERUN_NOT_AUTHORIZED"
    CACHE_READY_FALSE = "CACHE_READY_FALSE"
    EXECUTABLE_FALSE = "EXECUTABLE_FALSE"
    TRAINING_INELIGIBLE = "TRAINING_INELIGIBLE"


@dataclass(slots=True)
class AlternateCleanroomImageProvenanceConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_alternate_cleanroom_image_provenance")
    search_roots: list[Path] = field(default_factory=list)
    target_image: str = ""
    target_digest: str = ""
    max_files_per_root: int = 5000


class ProgramBenchAlternateCleanroomImageProvenance:
    def __init__(self, config: AlternateCleanroomImageProvenanceConfig | None = None) -> None:
        self.config = config or AlternateCleanroomImageProvenanceConfig()

    def discover(self, operator_request_path: Path) -> dict[str, Any]:
        request_path = self._resolve(operator_request_path)
        request = _read_json(request_path) if request_path.is_file() else {}
        if not request_path.is_file() or not verify_operator_provenance_request_packet_record(
            request
        ):
            return self._write_blocked(
                status=AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_BLOCKED_NO_REQUEST.value,
                decision=AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_BLOCKED.value,
                request_path=request_path,
                request=request,
                searched=[],
                candidates=[],
                reasons=["operator_provenance_request_missing_or_invalid"],
            )

        image = str(request.get("image_reference") or "")
        digest = str(request.get("image_digest") or "")
        if self.config.target_image and image != self.config.target_image:
            return self._write_blocked(
                status=AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_BLOCKED_IMAGE_MISMATCH.value,
                decision=AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_BLOCKED.value,
                request_path=request_path,
                request=request,
                searched=[],
                candidates=[],
                reasons=["image_reference_mismatch"],
            )
        if self.config.target_digest and digest != self.config.target_digest:
            return self._write_blocked(
                status=AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_BLOCKED_DIGEST_MISMATCH.value,
                decision=AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_BLOCKED.value,
                request_path=request_path,
                request=request,
                searched=[],
                candidates=[],
                reasons=["image_digest_mismatch"],
            )

        chain_errors = self._validate_request_chain(request)
        if chain_errors:
            return self._write_blocked(
                status=AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_BLOCKED_CHAIN_INVALID.value,
                decision=AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_BLOCKED.value,
                request_path=request_path,
                request=request,
                searched=[],
                candidates=[],
                reasons=chain_errors,
            )

        searched, candidates = self._search_allowed_sources(
            original_image=image, original_digest=digest
        )
        exact = [
            c
            for c in candidates
            if c["classification"]
            == AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_FOUND_EXACT.value
        ]
        partial = [
            c
            for c in candidates
            if c["classification"]
            == AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_FOUND_PARTIAL.value
        ]
        blocked = [
            c
            for c in candidates
            if c["classification"]
            == AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_BLOCKED.value
        ]

        if exact:
            status = AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_FOUND_EXACT.value
            decision = (
                AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_ADMISSIBLE.value
            )
            selected = exact[0]
            reasons = ["exact_digest_source_recipe_and_fidelity_provenance_found"]
        elif partial:
            status = AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_FOUND_PARTIAL.value
            decision = AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_QUARANTINE_ONLY.value
            selected = partial[0]
            reasons = ["alternate_provenance_partial_only"]
        elif blocked:
            status = (
                AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_BLOCKED.value
            )
            decision = (
                AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_BLOCKED.value
            )
            selected = blocked[0]
            reasons = ["only_blocked_alternate_candidates_found"]
        else:
            status = AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_NOT_FOUND.value
            decision = (
                AlternateCleanroomImageProvenanceStatus.NO_ALTERNATE_IMAGE_CANDIDATE_FOUND.value
            )
            selected = {}
            reasons = ["no_explicit_alternate_cleanroom_candidate_found_in_allowed_sources"]

        fidelity_impact = _fidelity_impact(selected, bool(exact or partial))
        if (
            fidelity_impact["fidelity_change_required"]
            and status
            != AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_NOT_FOUND.value
        ):
            provenance_status = [
                status,
                AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_FIDELITY_CHANGE_REQUIRED.value,
            ]
        else:
            provenance_status = [status]
        record = make_alternate_cleanroom_image_provenance_record(
            status=status,
            decision=decision,
            original_image_reference=image,
            original_image_digest=digest,
            operator_provenance_request=_rel(self.config.root, request_path),
            searched_sources=searched,
            alternate_candidates=candidates,
            selected_candidate=selected,
            provenance_findings={
                "provenance_statuses": [*provenance_status, decision, *_blocked_statuses()],
                "exact_candidates": len(exact),
                "partial_candidates": len(partial),
                "blocked_candidates": len(blocked),
                "requires_exact_digest_source_provenance": True,
                "latest_or_name_only_rejected": any(
                    "latest_or_name_only_reference" in c.get("reasons", []) for c in blocked
                ),
                "inferred_officialness_rejected": any(
                    "inferred_officialness_only" in c.get("reasons", []) for c in blocked
                ),
            },
            benchmark_fidelity_impact=fidelity_impact,
            authorization=_authorization(
                candidate_found=bool(exact or partial), candidate_admitted=False
            ),
            reasons=reasons,
            cache_ready=False,
            executable=False,
        )
        path = write_alternate_cleanroom_image_provenance_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _validate_request_chain(self, request: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        decision_path = self._resolve(Path(str(request.get("rebuild_quarantine_decision") or "")))
        decision = _read_json(decision_path) if decision_path.is_file() else {}
        if not verify_rebuild_provenance_quarantine_decision_record(decision):
            return ["rebuild_quarantine_decision_missing_or_invalid"]
        image = str(request.get("image_reference") or "")
        digest = str(request.get("image_digest") or "")
        if str(decision.get("image_reference") or "") != image:
            errors.append("rebuild_quarantine_decision_image_mismatch")
        if str(decision.get("image_digest") or "") != digest:
            errors.append("rebuild_quarantine_decision_digest_mismatch")
        paths = {
            "remediation_plan": Path(str(decision.get("remediation_plan") or "")),
            "recipe_recovery": Path(str(decision.get("recipe_recovery") or "")),
            "provenance_gap": Path(str(decision.get("provenance_gap") or "")),
            "recipe_provenance_recovery": Path(
                str(decision.get("recipe_provenance_recovery") or "")
            ),
        }
        validators = {
            "remediation_plan": verify_cleanroom_image_remediation_plan_record,
            "recipe_recovery": verify_cleanroom_build_recipe_recovery_record,
            "provenance_gap": verify_cleanroom_build_recipe_provenance_gap_record,
            "recipe_provenance_recovery": verify_cleanroom_recipe_provenance_recovery_record,
        }
        for name, path in paths.items():
            resolved = self._resolve(path)
            record = _read_json(resolved) if str(path) and resolved.is_file() else {}
            if not validators[name](record):
                errors.append(f"{name}_missing_or_invalid")
                continue
            if str(record.get("image_reference") or "") != image:
                errors.append(f"{name}_image_mismatch")
            if str(record.get("image_digest") or "") != digest:
                errors.append(f"{name}_digest_mismatch")
        return errors

    def _search_allowed_sources(
        self, *, original_image: str, original_digest: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        roots = self.config.search_roots or _default_search_roots()
        searched: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
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
                else sorted(p for p in resolved.rglob("*.json") if p.is_file())
            )
            for path in files[: self.config.max_files_per_root]:
                entry["files_examined"] += 1
                candidate = _candidate_from_file(
                    path, self.config.root, original_image, original_digest
                )
                if candidate:
                    entry["matches"] += 1
                    candidates.append(candidate)
            if len(files) > self.config.max_files_per_root:
                entry["truncated"] = True
            searched.append(entry)
        candidates.sort(key=lambda item: (item["rank"], item["path"]))
        return searched, candidates

    def _write_blocked(
        self,
        *,
        status: str,
        decision: str,
        request_path: Path,
        request: dict[str, Any],
        searched: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        reasons: list[str],
    ) -> dict[str, Any]:
        record = make_alternate_cleanroom_image_provenance_record(
            status=status,
            decision=decision,
            original_image_reference=str(
                request.get("image_reference") or self.config.target_image
            ),
            original_image_digest=str(request.get("image_digest") or self.config.target_digest),
            operator_provenance_request=_rel(self.config.root, request_path),
            searched_sources=searched,
            alternate_candidates=candidates,
            provenance_findings={
                "provenance_statuses": [status, decision, *_blocked_statuses()],
                "requires_exact_digest_source_provenance": True,
            },
            benchmark_fidelity_impact={"fidelity_change_required": False, "impact": "unknown"},
            authorization=_authorization(candidate_found=False, candidate_admitted=False),
            reasons=reasons,
            cache_ready=False,
            executable=False,
        )
        path = write_alternate_cleanroom_image_provenance_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _candidate_from_file(
    path: Path, root: Path, original_image: str, original_digest: str
) -> dict[str, Any] | None:
    data = _read_json(path)
    if not data:
        return None
    if not bool(data.get("alternate_cleanroom_candidate")):
        return None
    image = str(
        data.get("alternate_image_reference")
        or data.get("image_reference")
        or data.get("image")
        or ""
    )
    digest = str(
        data.get("alternate_image_digest")
        or data.get("image_digest")
        or data.get("manifest_digest")
        or data.get("digest")
        or ""
    )
    if not image or image == original_image:
        return None
    if digest == original_digest:
        return None
    tag = str(data.get("tag") or "")
    source = str(
        data.get("source_registry")
        or data.get("source_url_or_registry")
        or data.get("registry")
        or ""
    )
    provenance = data.get("provenance") if isinstance(data.get("provenance"), dict) else {}
    fidelity = (
        data.get("benchmark_fidelity") if isinstance(data.get("benchmark_fidelity"), dict) else {}
    )

    has_digest = digest.startswith("sha256:")
    has_source = bool(source)
    has_recipe = bool(
        provenance.get("original_recipe")
        or provenance.get("recipe_digest")
        or provenance.get("reproducible_build_recipe")
    )
    has_base = bool(provenance.get("base_image_digest"))
    has_toolchain = bool(provenance.get("toolchain_provenance"))
    fidelity_declared = bool(fidelity.get("impact") or fidelity.get("fidelity_risk"))
    inferred_only = bool(data.get("inferred_officialness"))
    latest_or_name_only = tag == "latest" or not has_digest

    reasons: list[str] = []
    if latest_or_name_only:
        reasons.append("latest_or_name_only_reference")
    if inferred_only:
        reasons.append("inferred_officialness_only")
    if not has_source:
        reasons.append("missing_source_registry")
    if not fidelity_declared:
        reasons.append("missing_benchmark_fidelity_statement")
    if not has_recipe:
        reasons.append("missing_original_recipe_or_reproducible_recipe")
    if not has_base:
        reasons.append("missing_pinned_base_image_digest")
    if not has_toolchain:
        reasons.append("missing_toolchain_provenance")

    exact = (
        has_digest
        and has_source
        and has_recipe
        and has_base
        and has_toolchain
        and fidelity_declared
        and not inferred_only
    )
    partial = has_digest and has_source and not inferred_only and not exact
    if exact:
        classification = (
            AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_FOUND_EXACT.value
        )
        decision = (
            AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_ADMISSIBLE.value
        )
        rank = 0
    elif partial:
        classification = AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_FOUND_PARTIAL.value
        decision = (
            AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_QUARANTINE_ONLY.value
        )
        rank = 10
    else:
        classification = (
            AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_BLOCKED.value
        )
        decision = AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_BLOCKED.value
        rank = 20

    return {
        "path": _rel(root, path),
        "alternate_image_reference": image,
        "alternate_image_digest": digest,
        "source_registry": source,
        "tag": tag,
        "classification": classification,
        "decision": decision,
        "benchmark_fidelity": fidelity,
        "provenance_summary": {
            "digest_pinned": has_digest,
            "source_present": has_source,
            "recipe_present": has_recipe,
            "base_image_digest_present": has_base,
            "toolchain_provenance_present": has_toolchain,
            "fidelity_declared": fidelity_declared,
            "inferred_officialness": inferred_only,
        },
        "reasons": reasons,
        "rank": rank,
        "execution_allowed": False,
        "quarantine_only": classification
        != AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_FOUND_EXACT.value,
    }


def _fidelity_impact(candidate: dict[str, Any], found_candidate: bool) -> dict[str, Any]:
    if not found_candidate:
        return {
            "fidelity_change_required": False,
            "impact": "no_alternate_candidate_found",
            "benchmark_equivalence_proven": False,
        }
    fidelity = (
        candidate.get("benchmark_fidelity")
        if isinstance(candidate.get("benchmark_fidelity"), dict)
        else {}
    )
    impact = str(fidelity.get("impact") or fidelity.get("fidelity_risk") or "material")
    return {
        "fidelity_change_required": impact not in {"none", "equivalent"},
        "impact": impact,
        "benchmark_equivalence_proven": impact in {"none", "equivalent"},
        "bounded_rerun_revalidation_required": True,
        "alternate_candidate_itself_authorizes_execution": False,
    }


def _authorization(*, candidate_found: bool, candidate_admitted: bool) -> dict[str, bool]:
    return {
        "alternate_candidate_found": bool(candidate_found),
        "alternate_candidate_admitted": bool(candidate_admitted),
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
        AlternateCleanroomImageProvenanceStatus.DOCKER_PULL_NOT_AUTHORIZED.value,
        AlternateCleanroomImageProvenanceStatus.DOCKER_EXECUTION_NOT_AUTHORIZED.value,
        AlternateCleanroomImageProvenanceStatus.HYDRATION_NOT_AUTHORIZED.value,
        AlternateCleanroomImageProvenanceStatus.PROGRAMBENCH_RERUN_NOT_AUTHORIZED.value,
        AlternateCleanroomImageProvenanceStatus.CACHE_READY_FALSE.value,
        AlternateCleanroomImageProvenanceStatus.EXECUTABLE_FALSE.value,
        AlternateCleanroomImageProvenanceStatus.TRAINING_INELIGIBLE.value,
    ]


def _default_search_roots() -> list[Path]:
    return [
        Path("assurance/evidence/programbench_operator_provenance_requests"),
        Path("assurance/evidence/programbench_operator_artifact_admissions"),
        Path("assurance/evidence/programbench_dockerhub_manifest_provenance"),
        Path("assurance/evidence/programbench_cleanroom_image_hydration"),
        Path("assurance/evidence/programbench_alternate_cleanroom_image_provenance_candidates"),
        Path("assurance/config"),
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover alternate ProgramBench cleanroom image provenance candidates."
    )
    parser.add_argument("operator_provenance_request", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_alternate_cleanroom_image_provenance"),
    )
    parser.add_argument("--search-root", action="append", type=Path, default=[])
    parser.add_argument("--target-image", default="")
    parser.add_argument("--target-digest", default="")
    args = parser.parse_args()
    result = ProgramBenchAlternateCleanroomImageProvenance(
        AlternateCleanroomImageProvenanceConfig(
            root=args.root,
            output_dir=args.output_dir,
            search_roots=args.search_root,
            target_image=args.target_image,
            target_digest=args.target_digest,
        )
    ).discover(args.operator_provenance_request)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
