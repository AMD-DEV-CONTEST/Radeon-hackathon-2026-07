from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_region_preference import region_score  # noqa: E402
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


def main() -> int:
    root = ROOT / "data/v10_region_preferences"
    pairs = [json.loads(line) for line in (root / "pairs.jsonl").read_text(encoding="utf-8").splitlines() if line]
    assets = [json.loads(line) for line in (root / "assets.jsonl").read_text(encoding="utf-8").splitlines() if line]
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    failures: list[str] = []
    by_source = {row["source_id"]: row for row in assets}
    opened: dict[str, Image.Image] = {}
    for asset in assets:
        path = ROOT / asset["asset_path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != asset["asset_sha256"]:
            failures.append(f"asset_hash:{asset['source_id']}")
        opened[asset["source_id"]] = Image.open(path).convert("RGB")
    for pair in pairs:
        image = opened[pair["source_id"]]
        for name in ("chosen_region", "rejected_region"):
            region = pair[name]
            observed = region_score(image, tuple(region["box"]))
            if observed != region["metrics"]:
                failures.append(f"score_recount:{pair['pair_id']}:{name}")
        if pair["chosen_region"]["metrics"]["score"] <= pair["rejected_region"]["metrics"]["score"]:
            failures.append(f"nonpositive_margin:{pair['pair_id']}")
        material = {key: value for key, value in pair.items() if key != "content_sha256"}
        if stable_sha256(material) != pair["content_sha256"]:
            failures.append(f"pair_hash:{pair['pair_id']}")
        if pair["source_id"] not in by_source:
            failures.append(f"unknown_asset:{pair['pair_id']}")
    provider_counts = Counter(row["provider"] for row in assets)
    observed = {
        "pair_count": len(pairs),
        "asset_count": len(assets),
        "train_pair_count": sum(row["split"] == "train" for row in pairs),
        "validation_pair_count": sum(row["split"] == "validation" for row in pairs),
        "provider_asset_counts": dict(sorted(provider_counts.items())),
        "duplicate_pair_count": len(pairs) - len({row["content_sha256"] for row in pairs}),
        "nonpositive_margin_count": sum(row["score_margin"] <= 0 for row in pairs),
    }
    expected = {
        "pair_count": 2_000,
        "asset_count": 500,
        "train_pair_count": 1_800,
        "validation_pair_count": 200,
        "provider_asset_counts": {"art-institute-chicago": 250, "cleveland-museum-art": 250},
        "duplicate_pair_count": 0,
        "nonpositive_margin_count": 0,
    }
    for key, value in expected.items():
        if observed[key] != value or manifest.get(key) != value:
            failures.append(f"recount:{key}")
    report = {
        "schema": "ProofLaunchRegionPreferenceIndependentAuditV1",
        "status": "passed_independent_recount_not_training" if not failures else "failed",
        **observed,
        "all_asset_hashes_and_region_scores_recomputed": not failures,
        "failure_count": len(failures),
        "failures": failures[:100],
        "teacher_model_used": False,
        "human_reviewed": False,
        "training_observed": False,
        "manifest_sha256": manifest["manifest_sha256"],
    }
    output = ROOT / "evidence/v10/region-preferences-2k-independent-audit.json"
    atomic_write_text(output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
