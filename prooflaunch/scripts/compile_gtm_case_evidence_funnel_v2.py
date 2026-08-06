#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_case_evidence_funnel_v2 import (
    build_case_evidence_funnel_standard,
    compile_case_evidence_funnel_coverage,
    compile_seed_migration_queue,
    verify_case_evidence_funnel_coverage,
    verify_case_evidence_funnel_standard,
)


ROOT = Path(__file__).resolve().parents[1]


def _read_list(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get(key, payload if isinstance(payload, list) else [])
    if not isinstance(rows, list):
        raise ValueError(f"{path} must contain a JSON list or a {key!r} list")
    return rows


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile the fail-closed 81×200→40→10→5 GTM case evidence funnel."
    )
    parser.add_argument("--candidates", type=Path, default=ROOT / "data/gtm_case_funnel_v2/candidates.json")
    parser.add_argument(
        "--admitted-candidates",
        type=Path,
        default=ROOT / "data/gtm_case_funnel_v2/admitted-candidates.json",
        help="Optional sealed registry produced only by strict named-human admission.",
    )
    parser.add_argument("--mechanisms", type=Path, default=ROOT / "data/gtm_case_funnel_v2/mechanism_audits.json")
    parser.add_argument("--outcomes", type=Path, default=ROOT / "data/gtm_case_funnel_v2/outcome_audits.json")
    parser.add_argument("--blueprints", type=Path, default=ROOT / "data/gtm_case_funnel_v2/execution_blueprints.json")
    parser.add_argument(
        "--quality-seed",
        type=Path,
        default=ROOT / "evidence/v10/gtm-breakout-quality-team-seed-v1.json",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "evidence/v10/gtm-case-evidence-funnel-v2"
    )
    args = parser.parse_args()

    standard = build_case_evidence_funnel_standard()
    verify_case_evidence_funnel_standard(standard)
    base_candidates = _read_list(args.candidates, "candidates")
    admitted_candidates = _read_list(args.admitted_candidates, "candidates")
    coverage = compile_case_evidence_funnel_coverage(
        standard,
        [*base_candidates, *admitted_candidates],
        _read_list(args.mechanisms, "mechanism_audits"),
        _read_list(args.outcomes, "outcome_audits"),
        _read_list(args.blueprints, "execution_blueprints"),
    )
    verify_case_evidence_funnel_coverage(coverage)
    quality_seed = json.loads(args.quality_seed.read_text(encoding="utf-8"))
    migration = compile_seed_migration_queue(quality_seed, standard)

    _write(args.output_dir / "standard.json", standard)
    _write(args.output_dir / "coverage.json", coverage)
    _write(args.output_dir / "legacy-seed-migration-queue.json", migration)
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "subvertical_count": standard["subvertical_count"],
                "global_targets": standard["global_funnel_targets"],
                "global_counts": coverage["global_funnel_counts"],
                "base_candidate_record_count": len(base_candidates),
                "admitted_candidate_record_count": len(admitted_candidates),
                "coverage_gap_subvertical_count": coverage["coverage_gap_subvertical_count"],
                "legacy_seed_migration_item_count": migration["migration_item_count"],
                "completion_claim_allowed": coverage["completion_claim_allowed"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
