"""
rosetta_recall_eval.py — Recall@K validation for the Rosetta Stone.

Measures whether same-concept embeddings from different model architectures
align in Rosetta space well enough to retrieve each other.

Metric: Recall@K
  - Project N prompts through model A's encoder → Rosetta space
  - Project same N prompts through model B's encoder → Rosetta space
  - For each A_i, find nearest neighbor in {B_j}
  - Recall@1: does B_i rank #1?  (perfect alignment = 1.0)
  - Recall@3: does B_i rank in top 3?

Also produces:
  - Positive pair cosine distribution (same prompt, A vs B)
  - Negative pair cosine distribution (different prompts, A vs B)
  - Distribution overlap histogram (the key "no overlap" claim)

Usage:
  python rosetta_recall_eval.py \\
    --rosetta ~/.determinex/rosetta/rosetta_v1.pt \\
    --model-a llama --model-b mistral \\
    --embedding-cache /path/to/rosetta_cache/ \\
    --output-dir logs/rosetta_recall/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import torch

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("recall_eval")


def load_embeddings(cache_dir: Path, arch: str) -> torch.Tensor:
    """Load saved embedding cache from train_rosetta_bases.py extraction phase."""
    path = cache_dir / f"{arch}_embeddings.pt"
    if not path.exists():
        log.error("Embedding cache not found: %s", path)
        log.error("Run train_rosetta_bases.py first to extract embeddings.")
        sys.exit(1)
    data = torch.load(path, weights_only=True)
    if isinstance(data, dict):
        return data.get("embeddings", data.get("embs", list(data.values())[0]))
    return data


def load_rosetta(rosetta_path: Path):
    """Load and verify the Rosetta Stone weights."""
    import hashlib

    raw = rosetta_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    log.info("Rosetta SHA256: %s", sha)
    stone = torch.load(rosetta_path, weights_only=True)
    log.info(
        "Rosetta version: %s  D_ROSETTA: %s",
        stone.get("version", "unknown"),
        stone.get("d_rosetta", "?"),
    )
    return stone, sha


def build_encoder(stone: dict, arch: str) -> torch.nn.Module:
    """Reconstruct encoder MLP from saved state dict."""
    key = f"{arch}_encoder"
    if key not in stone:
        available = [k for k in stone if k.endswith("_encoder")]
        log.error("No encoder for '%s'. Available: %s", arch, available)
        sys.exit(1)
    state = stone[key]
    dims = stone.get("dims", {})
    d_in = dims.get(arch, 4096)
    d_out = stone.get("d_rosetta", 4096)

    net = torch.nn.Sequential(
        torch.nn.Linear(d_in, d_out * 2),
        torch.nn.GELU(),
        torch.nn.Linear(d_out * 2, d_out),
    )
    net.load_state_dict(state)
    net.eval()
    return net


@torch.no_grad()
def project(embeddings: torch.Tensor, encoder: torch.nn.Module) -> torch.Tensor:
    """Project embeddings through encoder, L2-normalize."""
    proj = encoder(embeddings.float())
    return torch.nn.functional.normalize(proj, dim=-1)


def recall_at_k(proj_a: torch.Tensor, proj_b: torch.Tensor, k: int = 1) -> float:
    """
    For each i, check if proj_b[i] is in the top-k nearest neighbors
    of proj_a[i] within {proj_b[j] for all j}.
    """
    n = proj_a.shape[0]
    hits = 0
    sim = proj_a @ proj_b.T  # [N, N] cosine similarity matrix
    for i in range(n):
        row = sim[i]
        top_k = torch.topk(row, k=min(k, n)).indices.tolist()
        if i in top_k:
            hits += 1
    return hits / n


def cosine_distributions(
    proj_a: torch.Tensor, proj_b: torch.Tensor
) -> tuple[np.ndarray, np.ndarray]:
    """
    Returns (positive_cosines, negative_cosines).
    Positive: same-index pairs (i, i).
    Negative: random cross-index pairs (i, j where j != i).
    """
    n = proj_a.shape[0]
    sim = proj_a @ proj_b.T  # [N, N]

    pos = sim.diagonal().cpu().numpy()

    # Sample N negative pairs (i, j) where j != i
    neg_vals = []
    for i in range(n):
        j = (i + 1 + np.random.randint(n - 1)) % n  # guaranteed j != i
        neg_vals.append(sim[i, j].item())
    neg = np.array(neg_vals)

    return pos, neg


def main():
    ap = argparse.ArgumentParser(description="Rosetta Recall@K evaluation")
    ap.add_argument(
        "--rosetta", type=Path, default=Path.home() / ".determinex/rosetta/rosetta_v1.pt"
    )
    ap.add_argument(
        "--model-a", default="llama", help="First architecture name (must match key in dims dict)"
    )
    ap.add_argument("--model-b", default="mistral", help="Second architecture name")
    ap.add_argument(
        "--embedding-cache",
        type=Path,
        required=True,
        help="Directory containing {arch}_embeddings.pt files",
    )
    ap.add_argument("--output-dir", type=Path, default=Path("logs/rosetta_recall"))
    ap.add_argument("--k-values", nargs="+", type=int, default=[1, 3, 5])
    args = ap.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    log.info("Loading Rosetta Stone from %s", args.rosetta)
    stone, sha = load_rosetta(args.rosetta)

    log.info("Loading embeddings: %s and %s", args.model_a, args.model_b)
    embs_a = load_embeddings(args.embedding_cache, args.model_a)
    embs_b = load_embeddings(args.embedding_cache, args.model_b)

    n = min(embs_a.shape[0], embs_b.shape[0])
    embs_a = embs_a[:n]
    embs_b = embs_b[:n]
    log.info("Evaluating on %d prompt pairs", n)

    enc_a = build_encoder(stone, args.model_a)
    enc_b = build_encoder(stone, args.model_b)

    log.info("Projecting through Rosetta encoders...")
    proj_a = project(embs_a, enc_a)
    proj_b = project(embs_b, enc_b)

    results: dict = {
        "rosetta_sha256": sha,
        "model_a": args.model_a,
        "model_b": args.model_b,
        "n_pairs": n,
        "recall": {},
    }

    log.info("Computing Recall@K...")
    for k in args.k_values:
        r_ab = recall_at_k(proj_a, proj_b, k)
        r_ba = recall_at_k(proj_b, proj_a, k)
        sym = (r_ab + r_ba) / 2
        results["recall"][f"k={k}"] = {
            "A→B": round(r_ab, 4),
            "B→A": round(r_ba, 4),
            "symmetric": round(sym, 4),
        }
        log.info("  Recall@%d:  A→B=%.3f  B→A=%.3f  sym=%.3f", k, r_ab, r_ba, sym)

    log.info("Computing cosine distributions...")
    pos_cos, neg_cos = cosine_distributions(proj_a, proj_b)
    results["distributions"] = {
        "positive_mean": float(np.mean(pos_cos)),
        "positive_std": float(np.std(pos_cos)),
        "positive_min": float(np.min(pos_cos)),
        "positive_max": float(np.max(pos_cos)),
        "negative_mean": float(np.mean(neg_cos)),
        "negative_std": float(np.std(neg_cos)),
        "separation_gap": float(np.mean(pos_cos) - np.mean(neg_cos)),
    }
    log.info("  Positive pairs: mean=%.4f ± %.4f", np.mean(pos_cos), np.std(pos_cos))
    log.info("  Negative pairs: mean=%.4f ± %.4f", np.mean(neg_cos), np.std(neg_cos))
    log.info("  Separation gap: %.4f", np.mean(pos_cos) - np.mean(neg_cos))

    # Save raw distribution arrays for histogram plotting
    np.save(str(args.output_dir / "positive_cosines.npy"), pos_cos)
    np.save(str(args.output_dir / "negative_cosines.npy"), neg_cos)

    # Write JSON results
    out = args.output_dir / f"recall_{args.model_a}_vs_{args.model_b}.json"
    out.write_text(json.dumps(results, indent=2))
    log.info("Results written to %s", out)

    # Summary
    r1 = results["recall"].get("k=1", {}).get("symmetric", 0)
    gap = results["distributions"]["separation_gap"]
    print(f"\n{'=' * 50}")
    print(f"  Recall@1 (symmetric): {r1:.1%}")
    print(f"  Distribution gap:     {gap:.4f}")
    print(f"  {'STRONG' if r1 > 0.7 else 'MODERATE' if r1 > 0.4 else 'WEAK'} alignment")
    print(f"{'=' * 50}\n")

    if r1 < 0.5:
        log.warning("Recall@1 below 0.5 — consider more training epochs or data diversity.")
    if gap < 0.05:
        log.warning("Distribution gap below 0.05 — training data may lack semantic diversity.")


if __name__ == "__main__":
    main()
