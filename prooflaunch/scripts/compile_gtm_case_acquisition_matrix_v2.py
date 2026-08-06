from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.gtm_case_acquisition_matrix_v2 import (
    build_case_acquisition_matrix,
    verify_case_acquisition_matrix,
)


ROOT = Path(__file__).resolve().parents[1]
STANDARD_PATH = ROOT / "evidence/v10/gtm-case-evidence-funnel-v2/standard.json"
DISCOVERY_PATH = ROOT / "evidence/v10/gtm-gold-case-discovery-v2.json"
OUTPUT_PATH = ROOT / "evidence/v10/gtm-case-acquisition-matrix-v2.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    payload = build_case_acquisition_matrix(_load(STANDARD_PATH), _load(DISCOVERY_PATH))
    verify_case_acquisition_matrix(payload)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(OUTPUT_PATH),
        "subvertical_count": payload["subvertical_count"],
        "slot_count": payload["slot_count"],
        "query_task_count": payload["query_task_count"],
        "formal_candidate_count": payload["formal_candidate_count"],
        "provisional_discovery_lead_count": payload["provisional_discovery_lead_count"],
        "provisional_discovery_route_count": payload["provisional_discovery_route_count"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
