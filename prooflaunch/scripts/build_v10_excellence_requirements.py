#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.v10_excellence_gate import requirements_for_program


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "evidence" / "v10" / "program-manifest.json"
OUTPUT = ROOT / "evidence" / "v10" / "double-standard-requirements.json"


def main() -> None:
    program = json.loads(PROGRAM.read_text(encoding="utf-8"))
    requirements = requirements_for_program(program["todos"])
    records = [item.to_dict() for item in requirements]
    canonical = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload = {
        "schema": "ProofLaunchV10DoubleStandardRequirementsV1",
        "meaning": {
            "official_floor": (
                "Every TODO binds to the program-level official competition "
                "gate; administration and submission TODOs add the directly "
                "applicable eligibility, deliverable, PR, and Radeon facets."
            ),
            "overdelivery_gate": (
                "Additional falsifiable research, training, Radeon, 4A craft, "
                "and evidence requirements. The label 200% is not a numeric "
                "quality claim."
            ),
        },
        "truth_policy": (
            "A plan, teacher output, proxy, self-score, or local mechanism "
            "cannot substitute for required external evidence."
        ),
        "todo_count": len(records),
        "coverage": {
            "todos_with_applicable_official_floor": sum(
                bool(record["official_floor"]) for record in records
            ),
            "todos_with_direct_submission_floor": sum(
                len(record["official_floor"]) > 1 for record in records
            ),
            "todos_with_overdelivery_gate": sum(
                bool(record["overdelivery_gate"]) for record in records
            ),
            "todos_with_required_facets": sum(
                bool(record["required_facets"]) for record in records
            ),
            "todos_with_multigpu_program_binding": sum(
                "multi_gpu_program_binding" in record["required_facets"]
                for record in records
            ),
            "todos_requiring_direct_multigpu_observation": sum(
                "multi_gpu_runtime" in record["required_facets"]
                for record in records
            ),
            "proxy_external_evidence_allowed": False,
        },
        "requirements_sha256": hashlib.sha256(canonical).hexdigest(),
        "requirements": records,
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": payload["schema"],
                "todo_count": payload["todo_count"],
                "requirements_sha256": payload["requirements_sha256"],
                "output": str(OUTPUT),
            }
        )
    )


if __name__ == "__main__":
    main()
