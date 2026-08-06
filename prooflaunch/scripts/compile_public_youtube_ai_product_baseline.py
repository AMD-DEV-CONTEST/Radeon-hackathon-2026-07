#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_public_youtube_baseline import compile_public_youtube_baseline, verify


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/public-youtube-ai-product-baseline-analysis-v1.json"
SOURCE_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1/public-youtube-ai-product-baseline-v1"
OUTPUT = SOURCE_ROOT / "named-product-youtube-baseline.json"


def main() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    source_payloads = {}
    source_bindings = []
    for spec in config["sources"]:
        index = int(spec["source_index"])
        path = SOURCE_ROOT / f"source-{index:04d}/collector-output.jsonl"
        if not path.is_file():
            raise SystemExit(f"missing isolated collector log: {path}")
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(lines) != 1:
            raise SystemExit(f"expected one channel payload in {path}, found {len(lines)}")
        source_payloads[index] = json.loads(lines[0])
        source_bindings.append({
            "source_index": index,
            "product": spec["product"],
            "path": str(path.relative_to(ROOT)),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    payload = compile_public_youtube_baseline(config, source_payloads=source_payloads, source_bindings=source_bindings)
    verify(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT),
        "named_product_count": payload["named_product_count"],
        "full_sample_product_count": payload["full_sample_product_count"],
        "limited_sample_product_count": payload["limited_sample_product_count"],
        "outlier_pattern_count": len(payload["cross_product_outlier_pattern_counts"]),
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
