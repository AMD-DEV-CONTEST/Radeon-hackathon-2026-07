from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_all_subvertical_discovery_v2 import (
    build_all_subvertical_discovery,
    verify_all_subvertical_discovery,
)


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compile a zero-credit discovery ledger spanning all 81 subverticals.")
    parser.add_argument(
        "--targeted-leads-json",
        action="append",
        default=[],
        help="Additional public lead set; may be passed more than once.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/gtm-all-subvertical-discovery-v2.json"),
    )
    return parser.parse_args()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    standard = _load(ROOT / "evidence/v10/gtm-case-evidence-funnel-v2/standard.json")
    acquisition = _load(ROOT / "evidence/v10/gtm-case-acquisition-matrix-v2.json")
    gold = _load(ROOT / "evidence/v10/gtm-gold-case-discovery-v2.json")
    targeted_paths = [Path(value) for value in args.targeted_leads_json] or [
        ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave1-v2.json",
        ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave2-b2b-v2.json",
        ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave3-b2c-v2.json",
        ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave4-classified-v2.json",
        ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave5-indexes-v2.json",
        ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave5-rendered-indexes-v2.json",
        ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave6-sitemaps-v2.json",
        ROOT / "data/gtm_case_funnel_v2/all-subvertical-public-leads-wave7-classified-v2.json",
        ROOT / "data/gtm_case_funnel_v2/high-transparency-public-leads-wave8-v2.json",
    ]
    targeted_sets = []
    for path in targeted_paths:
        payload = _load(path)
        rows = payload.get("records", payload)
        if not isinstance(rows, list):
            raise SystemExit(f"{path} must contain a list or records list")
        targeted_sets.append((str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path), rows))
    payload = build_all_subvertical_discovery(standard, acquisition, gold, targeted_sets)
    verify_all_subvertical_discovery(payload)
    output = Path(args.output)
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "unique_discovery_lead_count": payload["unique_discovery_lead_count"],
        "provisionally_routed_lead_count": payload["provisionally_routed_lead_count"],
        "provisional_route_assignment_count": payload["provisional_route_assignment_count"],
        "subverticals_with_provisional_routes": payload["subverticals_with_provisional_routes"],
        "formal_candidate_count": payload["formal_candidate_count"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
