from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _load(path: Path) -> dict:
    with path.open() as handle:
        return json.load(handle)


def _aggregate(data: dict) -> dict:
    episodes = data["episodes_detail"]
    calls = sum(ep["inference_calls"] for ep in episodes)
    total_s = sum(ep["inference_total_seconds"] for ep in episodes)
    first_s = sum(ep["inference_first_ms"] for ep in episodes) / 1000.0
    steady_calls = calls - len(episodes)
    return {
        "success": sum(ep["success"] for ep in episodes),
        "episodes": len(episodes),
        "calls": calls,
        "first_mean_ms": first_s * 1000.0 / len(episodes),
        "steady_mean_ms": (total_s - first_s) * 1000.0 / steady_calls,
        "all_mean_ms": total_s * 1000.0 / calls,
        "rollout_wall_s": sum(ep["rollout_wall_seconds"] for ep in episodes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize paired eager/HIP Graph closed-loop results")
    parser.add_argument("root", type=Path)
    parser.add_argument("--episodes", type=int, default=5, help="Episodes per fruit used in result filenames")
    parser.add_argument("--candidate", default="hip_graph", help="Candidate result subdirectory")
    parser.add_argument("--candidate-label", default=None, help="Candidate label shown in the report")
    parser.add_argument("--csv-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()

    rows = []
    paired_matches = 0
    paired_total = 0
    exact_step_matches = 0
    suffix = f"_{args.episodes}ep.json"
    candidate_label = args.candidate_label or args.candidate.replace("_", " ").title()
    # Preserve the historical HIP Graph CSV schema used by the frozen result,
    # while newer/custom candidates use the generic candidate_* schema.
    csv_prefix = "hip_graph" if args.candidate == "hip_graph" else "candidate"
    candidate_success_key = f"{csv_prefix}_success"
    candidate_steady_key = f"{csv_prefix}_steady_ms"
    candidate_first_key = f"{csv_prefix}_first_ms"
    candidate_rollout_key = f"{csv_prefix}_rollout_s"
    for fruit in ("banana", "lemon", "plum"):
        eager = _load(args.root / "eager" / f"{fruit}{suffix}")
        graph = _load(args.root / args.candidate / f"{fruit}{suffix}")
        ea, ga = _aggregate(eager), _aggregate(graph)
        pairs = list(zip(eager["episodes_detail"], graph["episodes_detail"], strict=True))
        matches = sum(a["success"] == b["success"] for a, b in pairs)
        step_matches = sum(a["steps"] == b["steps"] for a, b in pairs)
        paired_matches += matches
        exact_step_matches += step_matches
        paired_total += len(pairs)
        rows.append({
            "fruit": fruit,
            "eager_success": f'{ea["success"]}/{ea["episodes"]}',
            candidate_success_key: f'{ga["success"]}/{ga["episodes"]}',
            "success_pair_matches": f"{matches}/{len(pairs)}",
            "exact_step_matches": f"{step_matches}/{len(pairs)}",
            "eager_steady_ms": ea["steady_mean_ms"],
            candidate_steady_key: ga["steady_mean_ms"],
            "steady_speedup": ea["steady_mean_ms"] / ga["steady_mean_ms"],
            "eager_first_ms": ea["first_mean_ms"],
            candidate_first_key: ga["first_mean_ms"],
            "eager_rollout_s": ea["rollout_wall_s"],
            candidate_rollout_key: ga["rollout_wall_s"],
        })

    fields = list(rows[0])
    csv_out = args.csv_out or args.root / "summary.csv"
    csv_out.parent.mkdir(parents=True, exist_ok=True)
    with csv_out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    eager_all = [_load(args.root / "eager" / f"{fruit}{suffix}") for fruit in ("banana", "lemon", "plum")]
    graph_all = [_load(args.root / args.candidate / f"{fruit}{suffix}") for fruit in ("banana", "lemon", "plum")]
    eager_flat = {"episodes_detail": sum((x["episodes_detail"] for x in eager_all), [])}
    graph_flat = {"episodes_detail": sum((x["episodes_detail"] for x in graph_all), [])}
    ea, ga = _aggregate(eager_flat), _aggregate(graph_flat)
    lines = [
        f"# Eager vs {candidate_label} closed-loop paired A/B",
        "",
        f"| Fruit | Eager success | {candidate_label} success | Success match | Exact steps | Eager steady ms | {candidate_label} steady ms | Speedup |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f'| {row["fruit"]} | {row["eager_success"]} | {row[candidate_success_key]} | '
            f'{row["success_pair_matches"]} | {row["exact_step_matches"]} | '
            f'{row["eager_steady_ms"]:.3f} | {row[candidate_steady_key]:.3f} | {row["steady_speedup"]:.3f}x |'
        )
    lines += [
        "",
        f'- Overall success: eager {ea["success"]}/{ea["episodes"]}, {candidate_label} {ga["success"]}/{ga["episodes"]}.',
        f'- Paired success agreement: {paired_matches}/{paired_total}; exact termination-step agreement: {exact_step_matches}/{paired_total}.',
        f'- Weighted steady latency: eager {ea["steady_mean_ms"]:.3f} ms, {candidate_label} {ga["steady_mean_ms"]:.3f} ms, speedup {ea["steady_mean_ms"] / ga["steady_mean_ms"]:.3f}x.',
        f'- Mean first-call latency per episode: eager {ea["first_mean_ms"]:.3f} ms, {candidate_label} {ga["first_mean_ms"]:.3f} ms.',
        f'- Total rollout wall time: eager {ea["rollout_wall_s"]:.3f} s, {candidate_label} {ga["rollout_wall_s"]:.3f} s.',
    ]
    markdown_out = args.markdown_out or args.root / "summary.md"
    markdown_out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"CSV: {csv_out}")
    print(f"Markdown: {markdown_out}")


if __name__ == "__main__":
    main()
