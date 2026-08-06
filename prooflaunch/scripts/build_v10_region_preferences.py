from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_bytes, atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_region_preference import ranked_regions, score_spread  # noqa: E402
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


PROVIDERS = ("art-institute-chicago", "cleveland-museum-art")
ASSETS_PER_PROVIDER = 250


def _download(row: dict[str, Any]) -> tuple[str, bytes | None, str | None]:
    try:
        request = urllib.request.Request(
            row["asset_url"], headers={"User-Agent": "ProofLaunch-CC0-RegionAudit/1.0"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(12 * 1024 * 1024 + 1)
        if not data or len(data) > 12 * 1024 * 1024:
            return row["source_id"], None, "empty_or_over_12mb"
        return row["source_id"], data, None
    except Exception as error:
        return row["source_id"], None, type(error).__name__


def main() -> int:
    output = ROOT / "data/v10_region_preferences"
    assets_dir = output / "assets"
    output.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        json.loads(line)
        for line in (ROOT / "data/v10_source_bundle/sources.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    candidates = [
        row for row in rows
        if row["provider"] in PROVIDERS
        and row["kind"] == "museum_visual"
        and row["license_id"] == "CC0-1.0"
        and row["training_allowed"]
        and not row["trademark_hold"]
    ]
    by_id = {row["source_id"]: row for row in candidates}
    download_rows = []
    for provider in PROVIDERS:
        download_rows.extend(
            sorted(
                (row for row in candidates if row["provider"] == provider),
                key=lambda row: row["source_id"],
            )[:400]
        )

    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(_download, row): row for row in download_rows}
        for future in as_completed(futures):
            source_id, data, error = future.result()
            if data is None:
                failures[source_id] = str(error)
                continue
            atomic_write_bytes(assets_dir / f"{source_id}.img", data)

    selected: list[dict[str, Any]] = []
    provider_counts = {provider: 0 for provider in PROVIDERS}
    rejected_low_signal = 0
    rejected_invalid = 0
    for row in sorted(download_rows, key=lambda item: (item["provider"], item["source_id"])):
        if provider_counts[row["provider"]] >= ASSETS_PER_PROVIDER:
            continue
        path = assets_dir / f"{row['source_id']}.img"
        if not path.is_file():
            continue
        try:
            with Image.open(path) as opened:
                image = opened.convert("RGB")
                ranked = ranked_regions(image)
        except (UnidentifiedImageError, OSError, ValueError):
            rejected_invalid += 1
            continue
        if score_spread(ranked) < 0.015:
            rejected_low_signal += 1
            continue
        selected.append({"source": row, "path": path, "image": image, "regions": ranked})
        provider_counts[row["provider"]] += 1
    if provider_counts != {provider: ASSETS_PER_PROVIDER for provider in PROVIDERS}:
        raise RuntimeError(f"insufficient accepted CC0 images: {provider_counts}")

    selected_asset_names = {item["path"].name for item in selected}
    for candidate_path in assets_dir.glob("*.img"):
        if candidate_path.name not in selected_asset_names:
            candidate_path.unlink()

    pairs: list[dict[str, Any]] = []
    asset_records = []
    for asset_index, item in enumerate(selected):
        row = item["source"]
        image = item["image"]
        regions = item["regions"]
        asset_sha = hashlib.sha256(item["path"].read_bytes()).hexdigest()
        split = "validation" if asset_index % 10 == 9 else "train"
        asset_records.append(
            {
                "source_id": row["source_id"],
                "provider": row["provider"],
                "asset_path": item["path"].relative_to(ROOT).as_posix(),
                "asset_sha256": asset_sha,
                "width": image.width,
                "height": image.height,
                "license_id": row["license_id"],
                "license_url": row["license_url"],
                "evidence_url": row["evidence_url"],
                "source_revision": row["revision"],
                "source_identity_sha256": row["identity_sha256"],
                "split": split,
            }
        )
        chosen = regions[0]
        for rejected_index, rejected in enumerate(regions[1:]):
            material = {
                "schema": "ProofLaunchRegionPreferenceV1",
                "pair_id": f"region-preference-{len(pairs) + 1:04d}",
                "source_id": row["source_id"],
                "provider": row["provider"],
                "split": split,
                "asset_path": item["path"].relative_to(ROOT).as_posix(),
                "asset_sha256": asset_sha,
                "image_size": [image.width, image.height],
                "chosen_region": chosen,
                "rejected_region": rejected,
                "preference_basis": "mechanical_entropy_edge_exposure_v1",
                "score_margin": round(
                    float(chosen["metrics"]["score"]) - float(rejected["metrics"]["score"]), 9
                ),
                "license_id": row["license_id"],
                "license_url": row["license_url"],
                "evidence_url": row["evidence_url"],
                "rights_verified": True,
                "teacher_model_used": False,
                "human_reviewed": False,
                "training_observed": False,
            }
            material["content_sha256"] = stable_sha256(material)
            pairs.append(material)
    if len(pairs) != 2_000:
        raise RuntimeError("region pair count drift")

    pair_text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in pairs) + "\n"
    asset_text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in asset_records) + "\n"
    atomic_write_text(output / "pairs.jsonl", pair_text)
    atomic_write_text(output / "assets.jsonl", asset_text)
    manifest = {
        "schema": "ProofLaunchRegionPreferenceCorpusV1",
        "pair_count": len(pairs),
        "asset_count": len(asset_records),
        "train_pair_count": sum(row["split"] == "train" for row in pairs),
        "validation_pair_count": sum(row["split"] == "validation" for row in pairs),
        "provider_asset_counts": provider_counts,
        "license_counts": {"CC0-1.0": len(asset_records)},
        "duplicate_pair_count": len(pairs) - len({row["content_sha256"] for row in pairs}),
        "nonpositive_margin_count": sum(row["score_margin"] <= 0 for row in pairs),
        "download_failure_count": len(failures),
        "rejected_low_signal_count": rejected_low_signal,
        "rejected_invalid_count": rejected_invalid,
        "pair_corpus_sha256": hashlib.sha256(pair_text.encode("utf-8")).hexdigest(),
        "asset_index_sha256": hashlib.sha256(asset_text.encode("utf-8")).hexdigest(),
        "teacher_model_used": False,
        "human_reviewed": False,
        "training_observed": False,
        "truth_boundary": (
            "This is a reproducible CC0 mechanical crop-region preference baseline. "
            "It is not VLM-teacher ranking, human 4A aesthetic review, or a trained-model result."
        ),
    }
    manifest["manifest_sha256"] = stable_sha256(dict(manifest))
    atomic_write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "passed_mechanical_region_preferences", **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
