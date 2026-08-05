#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.corpus_manager import verify_signature
from corpus.legacy_recovery.artifact_source_registry import ArtifactSourceRegistry
from corpus.legacy_recovery.artifact_trust_policy import evaluate_artifact_policy
from corpus.programbench.infra_failure_triage_record import (
    make_infra_failure_triage_record,
    write_infra_failure_triage_record,
)
from corpus.programbench.real_bounded_rerun_record import verify_real_rerun_record


class InfraFailureTriageStatus(str, Enum):
    INFRA_FAILURE_TRIAGED = "INFRA_FAILURE_TRIAGED"
    INFRA_FAILURE_UNRECOGNIZED = "INFRA_FAILURE_UNRECOGNIZED"
    MISSING_CLEANROOM_IMAGE = "MISSING_CLEANROOM_IMAGE"
    IMAGE_PRESENT_LOCAL = "IMAGE_PRESENT_LOCAL"
    IMAGE_MISSING_LOCAL = "IMAGE_MISSING_LOCAL"
    IMAGE_SOURCE_EXACT_REFERENCE_FOUND = "IMAGE_SOURCE_EXACT_REFERENCE_FOUND"
    IMAGE_SOURCE_AMBIGUOUS = "IMAGE_SOURCE_AMBIGUOUS"
    IMAGE_SOURCE_BLOCKED = "IMAGE_SOURCE_BLOCKED"
    IMAGE_RECOVERY_REQUIRES_OPERATOR = "IMAGE_RECOVERY_REQUIRES_OPERATOR"
    IMAGE_HYDRATION_READY_QUARANTINE_ONLY = "IMAGE_HYDRATION_READY_QUARANTINE_ONLY"
    IMAGE_HYDRATION_BLOCKED_NO_DIGEST = "IMAGE_HYDRATION_BLOCKED_NO_DIGEST"
    IMAGE_HYDRATION_BLOCKED_NO_PROVENANCE = "IMAGE_HYDRATION_BLOCKED_NO_PROVENANCE"
    IMAGE_HYDRATION_BLOCKED_POLICY = "IMAGE_HYDRATION_BLOCKED_POLICY"


ImageLister = Callable[[], list[str]]


@dataclass(slots=True)
class InfraFailureTriageConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_infra_failure_triage")
    provenance_roots: list[Path] = field(
        default_factory=lambda: [
            Path("assurance/evidence"),
            Path("T:/determinex_artifacts/provenance"),
        ]
    )
    artifact_sources_path: Path = Path("assurance/config/artifact_sources.json")
    image_lister: ImageLister | None = None


class ProgramBenchInfraFailureTriage:
    def __init__(self, config: InfraFailureTriageConfig | None = None) -> None:
        self.config = config or InfraFailureTriageConfig()
        self.source_registry = ArtifactSourceRegistry(
            self._resolve(self.config.artifact_sources_path)
        )

    def triage(self, source_record_path: Path) -> dict[str, Any]:
        path = self._resolve(source_record_path)
        record = _read_json(path)
        if not verify_real_rerun_record(record):
            return self._write_unrecognized(path, record, ["invalid_real_bounded_rerun_signature"])
        if str(record.get("status") or "") != "REAL_BOUNDED_RERUN_INFRA_FAILURE":
            return self._write_unrecognized(path, record, ["record_not_infra_failure"])

        combined = _combined_failure_text(record)
        missing_image = _extract_missing_image(combined)
        if not missing_image:
            return self._write_unrecognized(path, record, ["missing_image_reference_not_found"])

        failure_statuses = [InfraFailureTriageStatus.MISSING_CLEANROOM_IMAGE.value]
        local_status = self._local_image_status(missing_image)
        failure_statuses.append(local_status)

        provenance = self._classify_provenance(missing_image)
        failure_statuses.extend(
            status for status in provenance["statuses"] if status not in failure_statuses
        )
        source_status = str(provenance["source_status"])
        provenance_status = str(provenance["provenance_status"])

        allowed_actions = [
            "local inventory check",
            "exact provider lookup if configured",
            "operator-supplied digest/provenance",
        ]
        blocked_actions = [
            "docker pull latest",
            "broad web search",
            "inferred official image",
            "execution from quarantine",
            "public_untrusted direct hydration",
        ]
        recommendation = _recommendation(source_status, provenance_status)
        triage_record = make_infra_failure_triage_record(
            status=InfraFailureTriageStatus.INFRA_FAILURE_TRIAGED.value,
            source_record=_rel(self.config.root, path),
            packet_id=str(record.get("packet_id") or ""),
            target=dict(record.get("target") or {}),
            failure_type=InfraFailureTriageStatus.MISSING_CLEANROOM_IMAGE.value,
            missing_image=missing_image,
            local_image_status=local_status,
            source_status=source_status,
            provenance_status=provenance_status,
            failure_statuses=failure_statuses,
            allowed_actions=allowed_actions,
            blocked_actions=blocked_actions,
            recovery_recommendation=recommendation,
            evidence={
                "source_record_status": str(record.get("status") or ""),
                "source_record_verified": True,
                "rerun_scope": record.get("rerun_scope") or {},
                "provenance_matches": provenance["matches"],
                "read_only_local_image_inspection": self.config.image_lister is not None,
            },
        )
        output_path = write_infra_failure_triage_record(
            triage_record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(output_path), "record": triage_record}

    def _write_unrecognized(
        self, source_record_path: Path, source_record: dict[str, Any], reasons: list[str]
    ) -> dict[str, Any]:
        triage_record = make_infra_failure_triage_record(
            status=InfraFailureTriageStatus.INFRA_FAILURE_UNRECOGNIZED.value,
            source_record=_rel(self.config.root, source_record_path),
            packet_id=str(source_record.get("packet_id") or ""),
            target=dict(source_record.get("target") or {}),
            failure_type=InfraFailureTriageStatus.INFRA_FAILURE_UNRECOGNIZED.value,
            failure_statuses=[InfraFailureTriageStatus.INFRA_FAILURE_UNRECOGNIZED.value],
            allowed_actions=["manual infra failure classification"],
            blocked_actions=["rerun without recognized infra triage"],
            recovery_recommendation="Classify the infra failure before any new rerun attempt.",
            evidence={"reasons": reasons},
        )
        output_path = write_infra_failure_triage_record(
            triage_record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(output_path), "record": triage_record}

    def _local_image_status(self, image: str) -> str:
        if self.config.image_lister is None:
            return InfraFailureTriageStatus.IMAGE_MISSING_LOCAL.value
        try:
            local_images = set(self.config.image_lister())
        except Exception:
            return InfraFailureTriageStatus.IMAGE_MISSING_LOCAL.value
        return (
            InfraFailureTriageStatus.IMAGE_PRESENT_LOCAL.value
            if image in local_images
            else InfraFailureTriageStatus.IMAGE_MISSING_LOCAL.value
        )

    def _classify_provenance(self, image: str) -> dict[str, Any]:
        matches = self._find_provenance_matches(image)
        if not matches:
            return {
                "statuses": [
                    InfraFailureTriageStatus.IMAGE_RECOVERY_REQUIRES_OPERATOR.value,
                    InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_NO_PROVENANCE.value,
                ],
                "source_status": InfraFailureTriageStatus.IMAGE_RECOVERY_REQUIRES_OPERATOR.value,
                "provenance_status": InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_NO_PROVENANCE.value,
                "matches": [],
            }
        identities = {
            (
                str(row.get("source") or ""),
                str(row.get("resolved_digest") or row.get("digest") or ""),
                str(row.get("revision") or ""),
            )
            for row in matches
        }
        compact_matches = [_compact_provenance(row) for row in matches]
        if len(identities) > 1:
            return {
                "statuses": [InfraFailureTriageStatus.IMAGE_SOURCE_AMBIGUOUS.value],
                "source_status": InfraFailureTriageStatus.IMAGE_SOURCE_AMBIGUOUS.value,
                "provenance_status": InfraFailureTriageStatus.IMAGE_SOURCE_AMBIGUOUS.value,
                "matches": compact_matches,
            }

        row = matches[0]
        if _is_quarantine_only(row):
            return {
                "statuses": [
                    InfraFailureTriageStatus.IMAGE_SOURCE_EXACT_REFERENCE_FOUND.value,
                    InfraFailureTriageStatus.IMAGE_HYDRATION_READY_QUARANTINE_ONLY.value,
                ],
                "source_status": InfraFailureTriageStatus.IMAGE_SOURCE_EXACT_REFERENCE_FOUND.value,
                "provenance_status": InfraFailureTriageStatus.IMAGE_HYDRATION_READY_QUARANTINE_ONLY.value,
                "matches": compact_matches,
            }
        digest = str(row.get("resolved_digest") or row.get("digest") or "")
        tag = str(row.get("tag") or "")
        artifact_id = str(row.get("artifact_id") or row.get("image") or "")
        if not digest.startswith("sha256:") or tag == "latest" or artifact_id.endswith(":latest"):
            return {
                "statuses": [
                    InfraFailureTriageStatus.IMAGE_SOURCE_BLOCKED.value,
                    InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_NO_DIGEST.value,
                ],
                "source_status": InfraFailureTriageStatus.IMAGE_SOURCE_BLOCKED.value,
                "provenance_status": InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_NO_DIGEST.value,
                "matches": compact_matches,
            }

        source = self.source_registry.get(str(row.get("source") or ""))
        candidate = {
            "artifact_id": artifact_id,
            "artifact_type": str(row.get("artifact_type") or "oci_image"),
            "source": str(row.get("source") or ""),
            "resolved_digest": digest,
            "tag": tag,
            "trust_level": str(row.get("trust_level") or ""),
            "security_scan": row.get("security_scan") or {},
        }
        decision = evaluate_artifact_policy(candidate, source)
        if not decision.allowed or str(row.get("trust_level") or "") == "public_untrusted":
            return {
                "statuses": [
                    InfraFailureTriageStatus.IMAGE_SOURCE_BLOCKED.value,
                    InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_POLICY.value,
                ],
                "source_status": InfraFailureTriageStatus.IMAGE_SOURCE_BLOCKED.value,
                "provenance_status": InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_POLICY.value,
                "matches": compact_matches,
            }

        if row.get("_sig") and not verify_signature(row):
            return {
                "statuses": [
                    InfraFailureTriageStatus.IMAGE_SOURCE_BLOCKED.value,
                    InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_NO_PROVENANCE.value,
                ],
                "source_status": InfraFailureTriageStatus.IMAGE_SOURCE_BLOCKED.value,
                "provenance_status": InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_NO_PROVENANCE.value,
                "matches": compact_matches,
            }
        return {
            "statuses": [InfraFailureTriageStatus.IMAGE_SOURCE_EXACT_REFERENCE_FOUND.value],
            "source_status": InfraFailureTriageStatus.IMAGE_SOURCE_EXACT_REFERENCE_FOUND.value,
            "provenance_status": InfraFailureTriageStatus.IMAGE_SOURCE_EXACT_REFERENCE_FOUND.value,
            "matches": compact_matches,
        }

    def _find_provenance_matches(self, image: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for root in self.config.provenance_roots:
            resolved = self._resolve(root)
            if not resolved.exists():
                continue
            for path in sorted(resolved.rglob("*.json")):
                data = _read_json_silent(path)
                if isinstance(data, dict) and _matches_image(data, image):
                    out.append(data)
        return out

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


def _combined_failure_text(record: dict[str, Any]) -> str:
    outcome = record.get("outcome") if isinstance(record.get("outcome"), dict) else {}
    pieces = [
        str(record.get("status") or ""),
        "\n".join(str(item) for item in (record.get("reasons") or [])),
        str(outcome.get("stdout") or ""),
        str(outcome.get("stderr") or ""),
        str(outcome.get("error") or ""),
        str(outcome.get("message") or ""),
    ]
    return "\n".join(pieces)


def _extract_missing_image(text: str) -> str:
    patterns = [
        r"FAIL image missing:\s*([^\s]+)",
        r"No such image:\s*([^\s]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip().rstrip(".")
    return ""


def _matches_image(row: dict[str, Any], image: str) -> bool:
    fields = (
        "artifact_id",
        "image",
        "task_image",
        "missing_image",
        "oci_image",
    )
    return any(str(row.get(field) or "") == image for field in fields)


def _is_quarantine_only(row: dict[str, Any]) -> bool:
    if row.get("quarantine_only") is True:
        return True
    allowed_use = row.get("allowed_use")
    return isinstance(allowed_use, list) and "quarantine_only" in allowed_use


def _compact_provenance(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": str(row.get("artifact_id") or row.get("image") or ""),
        "artifact_type": str(row.get("artifact_type") or ""),
        "source": str(row.get("source") or ""),
        "resolved_digest": str(row.get("resolved_digest") or row.get("digest") or ""),
        "tag": str(row.get("tag") or ""),
        "trust_level": str(row.get("trust_level") or ""),
        "quarantine_only": bool(row.get("quarantine_only")),
    }


def _recommendation(source_status: str, provenance_status: str) -> str:
    if provenance_status == InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_NO_PROVENANCE.value:
        return "Operator must supply an exact digest/source provenance record before cleanroom image hydration."
    if source_status == InfraFailureTriageStatus.IMAGE_SOURCE_AMBIGUOUS.value:
        return "Resolve artifact ambiguity before hydration."
    if provenance_status == InfraFailureTriageStatus.IMAGE_HYDRATION_READY_QUARANTINE_ONLY.value:
        return "Artifact may stay in quarantine metadata, but cannot execute until scanned, pinned, and admitted."
    if provenance_status == InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_POLICY.value:
        return "Artifact source policy blocks hydration; provide trusted provenance or a policy-approved source."
    return "Exact provenance exists; run the cleanroom image hydration gate before any replay."


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return data if isinstance(data, dict) else {}


def _read_json_silent(path: Path) -> dict[str, Any]:
    try:
        return _read_json(path)
    except Exception:
        return {}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Triage a ProgramBench real bounded rerun infra failure."
    )
    parser.add_argument("source_record", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_infra_failure_triage"),
    )
    args = parser.parse_args()
    result = ProgramBenchInfraFailureTriage(
        InfraFailureTriageConfig(root=args.root, output_dir=args.output_dir)
    ).triage(args.source_record)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
