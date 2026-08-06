#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_outcome_blueprint_pipeline_v2 import (
    compile_blueprint_review_queue,
    compile_mechanism_family_index,
    compile_outcome_review_queue,
    verify_blueprint_review_queue,
    verify_mechanism_family_index,
    verify_outcome_review_queue,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    corpus = json.loads((ROOT / "data/gtm_case_funnel_v2/candidates.json").read_text(encoding="utf-8"))
    candidates = corpus["candidates"]
    outcome_queue = compile_outcome_review_queue(candidates, [], [])
    verify_outcome_review_queue(outcome_queue)
    blueprint_queue = compile_blueprint_review_queue(candidates, [], [])
    verify_blueprint_review_queue(blueprint_queue)
    families = compile_mechanism_family_index([], [])
    verify_mechanism_family_index(families)
    payload = {
        "schema": "ProofLaunchGTMOutcomeBlueprintPipelineBundleV2",
        "source_candidate_corpus_sha256": corpus["content_sha256"],
        "outcome_review_queue": outcome_queue,
        "blueprint_review_queue": blueprint_queue,
        "mechanism_family_index": families,
        "current_blocker": "No mechanism audit has named human approval; therefore outcome review, execution blueprints, and mechanism-family promotion remain empty.",
        "truth_boundary": "The executable contracts are proven by tests; current production evidence remains zero beyond the human mechanism-review gate.",
    }
    unsigned = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    import hashlib
    payload["content_sha256"] = hashlib.sha256(unsigned).hexdigest()
    output = ROOT / "evidence/v10/gtm-outcome-blueprint-pipeline-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "outcome_review_items": outcome_queue["selected_review_item_count"],
        "blueprint_review_items": blueprint_queue["selected_review_item_count"],
        "mechanism_families": families["family_count"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
