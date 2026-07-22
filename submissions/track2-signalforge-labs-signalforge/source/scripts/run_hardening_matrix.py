#!/usr/bin/env python3
"""Execute the frozen Sprint 12 adversarial gates and emit a deterministic report."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "configs" / "hardening" / "sprint12-matrix-v1.json"
DEFAULT_OUTPUT = ROOT / "evidence" / "hardening-matrix.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(matrix: dict) -> None:
    if matrix.get("schema_version") != "signalforge/hardening-matrix/v1":
        raise ValueError("unsupported hardening matrix schema")
    gates = matrix.get("gates", [])
    cases = matrix.get("cases", [])
    if not gates or not cases:
        raise ValueError("hardening matrix requires gates and cases")
    gate_ids = set()
    for gate in gates:
        gate_id = gate.get("gate_id", "")
        command = gate.get("command", [])
        sources = gate.get("sources", [])
        if not gate_id or gate_id in gate_ids or not command or not sources:
            raise ValueError(f"invalid or duplicate gate {gate_id!r}")
        gate_ids.add(gate_id)
        for source in sources:
            if not (ROOT / source).is_file():
                raise ValueError(f"gate {gate_id!r} references missing source {source!r}")
    case_ids = set()
    allowed_severity = {"critical", "high", "medium", "low"}
    for case in cases:
        case_id = case.get("case_id", "")
        if not case_id or case_id in case_ids:
            raise ValueError(f"invalid or duplicate case {case_id!r}")
        case_ids.add(case_id)
        if case.get("gate_id") not in gate_ids or case.get("severity") not in allowed_severity:
            raise ValueError(f"case {case_id!r} has invalid gate or severity")
        for field in ("domain", "threat", "owner", "expected", "mitigation", "residual_risk"):
            if not case.get(field):
                raise ValueError(f"case {case_id!r} is missing {field}")


def execute(matrix: dict, matrix_path: Path) -> dict:
    gate_reports = []
    for gate in matrix["gates"]:
        command = gate["command"]
        subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        gate_reports.append({
            "gate_id": gate["gate_id"],
            "command": command,
            "status": "passed",
            "source_hashes": [
                {"path": source, "sha256": sha256(ROOT / source)}
                for source in gate["sources"]
            ],
        })
    severity_counts = {
        severity: sum(1 for case in matrix["cases"] if case["severity"] == severity)
        for severity in ("critical", "high", "medium", "low")
    }
    return {
        "schema_version": "signalforge/hardening-report/v1",
        "matrix_id": matrix["matrix_id"],
        "matrix_path": str(matrix_path.resolve().relative_to(ROOT)),
        "matrix_sha256": sha256(matrix_path),
        "status": "passed",
        "cases": len(matrix["cases"]),
        "severity_counts": severity_counts,
        "release_blockers": 0,
        "gates": gate_reports,
        "scope": "Repository-executable adversarial gates; residual risks remain authoritative and this report is not a universal factual-accuracy claim.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    validate(matrix)
    report = execute(matrix, args.matrix)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != encoded:
            raise SystemExit(f"stale hardening report: {args.output}")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
