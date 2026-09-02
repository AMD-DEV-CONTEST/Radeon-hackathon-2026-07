#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.official_artifact_security_decision_record import (
    make_official_artifact_security_decision_record,
    write_official_artifact_security_decision_record,
)
from corpus.programbench.upstream_artifact_authority_recheck_record import (
    verify_upstream_artifact_authority_recheck_record,
)


class OfficialArtifactSecurityDecisionStatus(str, Enum):
    OFFICIAL_ARTIFACT_SECURITY_DECISION_WRITTEN = "OFFICIAL_ARTIFACT_SECURITY_DECISION_WRITTEN"
    OFFICIAL_ARTIFACT_EXECUTION_BLOCKED_SCAN_FAILED = (
        "OFFICIAL_ARTIFACT_EXECUTION_BLOCKED_SCAN_FAILED"
    )
    OFFICIAL_ARTIFACT_EXECUTION_REQUIRES_POLICY_EXCEPTION = (
        "OFFICIAL_ARTIFACT_EXECUTION_REQUIRES_POLICY_EXCEPTION"
    )
    OFFICIAL_ARTIFACT_EXECUTION_REQUIRES_STRONGER_SANDBOX = (
        "OFFICIAL_ARTIFACT_EXECUTION_REQUIRES_STRONGER_SANDBOX"
    )
    OFFICIAL_ARTIFACT_METADATA_ONLY_ADMITTED = "OFFICIAL_ARTIFACT_METADATA_ONLY_ADMITTED"
    OFFICIAL_ARTIFACT_SECURITY_DECISION_BLOCKED_NO_AUTHORITY_RECHECK = (
        "OFFICIAL_ARTIFACT_SECURITY_DECISION_BLOCKED_NO_AUTHORITY_RECHECK"
    )
    CACHE_READY_FALSE = "CACHE_READY_FALSE"
    EXECUTABLE_FALSE = "EXECUTABLE_FALSE"
    TRAINING_INELIGIBLE = "TRAINING_INELIGIBLE"


@dataclass(slots=True)
class OfficialArtifactSecurityDecisionConfig:
    root: Path = Path(".")
    output_dir: Path = Path("assurance/evidence/programbench_official_artifact_security_decisions")


class ProgramBenchOfficialArtifactSecurityDecision:
    def __init__(self, config: OfficialArtifactSecurityDecisionConfig | None = None) -> None:
        self.config = config or OfficialArtifactSecurityDecisionConfig()

    def decide(self, upstream_authority_recheck_path: Path) -> dict[str, Any]:
        path = self._resolve(upstream_authority_recheck_path)
        recheck = _read_json(path) if path.is_file() else {}
        if not recheck or not verify_upstream_artifact_authority_recheck_record(recheck):
            record = self._record(
                status=OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_SECURITY_DECISION_BLOCKED_NO_AUTHORITY_RECHECK.value,
                decision=OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_SECURITY_DECISION_BLOCKED_NO_AUTHORITY_RECHECK.value,
                recheck_path=path,
                recheck=recheck,
                statuses=[
                    OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_SECURITY_DECISION_BLOCKED_NO_AUTHORITY_RECHECK.value
                ],
                reasons=["upstream_artifact_authority_recheck_missing_or_invalid"],
            )
            return self._write(record)

        upstream = str(recheck.get("upstream_benchmark_artifact_authority") or "")
        execution_policy = str(recheck.get("execution_security_policy") or "")
        if upstream != "PRESENT":
            decision = "OFFICIAL_ARTIFACT_SECURITY_DECISION_BLOCKED_AUTHORITY_NOT_PRESENT"
            statuses = [decision]
            reasons = ["upstream_benchmark_artifact_authority_not_present"]
        elif execution_policy == "BLOCKED_SCAN_FAILED":
            decision = OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_EXECUTION_BLOCKED_SCAN_FAILED.value
            statuses = [
                OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_METADATA_ONLY_ADMITTED.value,
                OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_EXECUTION_BLOCKED_SCAN_FAILED.value,
            ]
            reasons = ["official_artifact_authority_present_but_security_scan_failed"]
        elif execution_policy == "BLOCKED_POLICY_REVIEW_REQUIRED":
            decision = OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_EXECUTION_REQUIRES_POLICY_EXCEPTION.value
            statuses = [
                OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_METADATA_ONLY_ADMITTED.value,
                OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_EXECUTION_REQUIRES_POLICY_EXCEPTION.value,
                OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_EXECUTION_REQUIRES_STRONGER_SANDBOX.value,
            ]
            reasons = ["official_artifact_authority_present_but_policy_review_required"]
        else:
            decision = "OFFICIAL_ARTIFACT_SECURITY_DECISION_INCONCLUSIVE"
            statuses = [decision]
            reasons = ["execution_security_policy_inconclusive"]

        record = self._record(
            status=OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_SECURITY_DECISION_WRITTEN.value,
            decision=decision,
            recheck_path=path,
            recheck=recheck,
            statuses=[
                OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_SECURITY_DECISION_WRITTEN.value,
                *statuses,
                OfficialArtifactSecurityDecisionStatus.CACHE_READY_FALSE.value,
                OfficialArtifactSecurityDecisionStatus.EXECUTABLE_FALSE.value,
                OfficialArtifactSecurityDecisionStatus.TRAINING_INELIGIBLE.value,
            ],
            reasons=[*reasons, "cache_ready_false", "executable_false", "training_eligible_false"],
        )
        return self._write(record)

    def _record(
        self,
        *,
        status: str,
        decision: str,
        recheck_path: Path,
        recheck: dict[str, Any],
        statuses: list[str],
        reasons: list[str],
    ) -> dict[str, Any]:
        return make_official_artifact_security_decision_record(
            status=status,
            decision=decision,
            instance_id=str(recheck.get("instance_id") or ""),
            image_reference=str(recheck.get("image_reference") or ""),
            image_digest=str(recheck.get("image_digest") or ""),
            upstream_authority_recheck=_rel(self.config.root, recheck_path),
            security_findings={
                "decision_statuses": list(dict.fromkeys(statuses)),
                "upstream_benchmark_artifact_authority": recheck.get(
                    "upstream_benchmark_artifact_authority"
                ),
                "rebuild_provenance_authority": recheck.get("rebuild_provenance_authority"),
                "remediation_authority": recheck.get("remediation_authority"),
                "execution_security_policy": recheck.get("execution_security_policy"),
                "scan_status": (recheck.get("verification") or {}).get("scan_status")
                if isinstance(recheck.get("verification"), dict)
                else "",
                "hydration_policy_result": (recheck.get("verification") or {}).get(
                    "hydration_policy_result"
                )
                if isinstance(recheck.get("verification"), dict)
                else "",
                "official_artifact_metadata_only": decision
                in {
                    OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_EXECUTION_BLOCKED_SCAN_FAILED.value,
                    OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_EXECUTION_REQUIRES_POLICY_EXCEPTION.value,
                    OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_EXECUTION_REQUIRES_STRONGER_SANDBOX.value,
                },
            },
            authorization={
                "metadata_only_admitted": decision
                != OfficialArtifactSecurityDecisionStatus.OFFICIAL_ARTIFACT_SECURITY_DECISION_BLOCKED_NO_AUTHORITY_RECHECK.value,
                "security_policy_exception_granted": False,
                "stronger_sandbox_approved": False,
                "docker_pull_authorized": False,
                "docker_execution_authorized": False,
                "hydration_authorized": False,
                "programbench_rerun_authorized": False,
                "cache_ready": False,
                "executable": False,
                "training_eligible": False,
            },
            reasons=reasons,
            cache_ready=False,
            executable=False,
        )

    def _write(self, record: dict[str, Any]) -> dict[str, Any]:
        path = write_official_artifact_security_decision_record(
            record, self._resolve(self.config.output_dir)
        )
        return {"record_path": str(path), "record": record}

    def _resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.config.root / path


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
        description="Decide official ProgramBench artifact security admission after authority recheck."
    )
    parser.add_argument("upstream_authority_recheck", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_official_artifact_security_decisions"),
    )
    args = parser.parse_args()
    result = ProgramBenchOfficialArtifactSecurityDecision(
        OfficialArtifactSecurityDecisionConfig(root=args.root, output_dir=args.output_dir)
    ).decide(args.upstream_authority_recheck)
    print(json.dumps(result["record"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
