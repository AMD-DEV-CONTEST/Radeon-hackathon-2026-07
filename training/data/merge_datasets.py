"""Merge all training datasets into a unified JSONL for SFT.

Combines FNSPID, FinGPT, and NL→DSL pairs into a single
training file with consistent format. Supports weighted sampling
based on source_weights configuration.
"""

from __future__ import annotations

import json
import random
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent / "data" / "processed"

# Default source weights (can be overridden by qlora_config.yaml)
DEFAULT_SOURCE_WEIGHTS: dict[str, float] = {
    "fnspid": 0.3,
    "fingpt": 0.3,
    "dsl-pairs": 0.4,
}


def merge_datasets(
    output_path: str | None = None,
    shuffle: bool = True,
    source_weights: dict[str, float] | None = None,
) -> str:
    """Merge all processed datasets into one JSONL with weighted sampling.

    Args:
        output_path: Custom output path.
        shuffle: Whether to shuffle the merged data.
        source_weights: Dict mapping source name to sampling weight.
            If None, uses DEFAULT_SOURCE_WEIGHTS. Sources not in the
            dict get weight 1.0.

    Returns:
        Path to the merged JSONL file.
    """
    weights = source_weights or DEFAULT_SOURCE_WEIGHTS

    # Group samples by source
    by_source: dict[str, list[dict]] = {}
    source_counts: dict[str, int] = {}

    input_files = [
        "fnspid_train.jsonl",
        "fingpt_train.jsonl",
        "dsl_pairs.jsonl",
    ]

    for fname in input_files:
        fpath = DATA_DIR / fname
        if not fpath.exists():
            print(f"[Merge] Skipping {fname} — not found")
            continue

        count = 0
        with open(fpath) as f:
            for line in f:
                sample = json.loads(line.strip())
                source = sample.get("source", "unknown")
                by_source.setdefault(source, []).append(sample)
                source_counts[source] = source_counts.get(source, 0) + 1
                count += 1
        print(f"[Merge] Loaded {count} samples from {fname}")

    # Apply weighted oversampling — normalize to proportional representation
    # Find the largest source, then scale others by weight ratio
    max_count = max(len(s) for s in by_source.values()) if by_source else 1
    total_weight = sum(weights.get(s, 1.0) for s in by_source)

    all_samples: list[dict] = []
    for source, samples in by_source.items():
        weight = weights.get(source, 1.0)
        # Target: proportional to weight, scaled to the largest source size
        target_count = int(max_count * weight / max(total_weight, 0.01))
        if target_count > len(samples):
            # Oversample with replacement
            random.seed(42)
            extra = [random.choice(samples) for _ in range(target_count - len(samples))]
            all_samples.extend(samples + extra)
        elif target_count < len(samples):
            # Downsample
            all_samples.extend(samples[:target_count])
        else:
            all_samples.extend(samples)
        print(f"[Merge] Source '{source}': {len(samples)} → {min(target_count, len(samples))} (weight={weight})")

    if shuffle:
        random.seed(42)
        random.shuffle(all_samples)

    output = output_path or str(DATA_DIR / "merged_train.jsonl")
    with open(output, "w") as f:
        for sample in all_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    print(f"[Merge] Total: {len(all_samples)} samples → {output}")
    print(f"[Merge] Sources: {source_counts}")
    return output


if __name__ == "__main__":
    merge_datasets()
