"""
pb_provenance_calibrate.py — Calibration pass for the provenance/attribution sidecar.

Walks corpus/programbench/locked/<tool>/ and runs check_provenance() on every
source/main.py (or compile.sh fallback) in each lock archive. Reports:
  - Per-tier tag rates (verbatim / substantial / inspiration)
  - Per-reference-source hit counts and license tiers
  - Most common filtered bigrams in hits (to tune _BIGRAM_STOPWORDS)
  - False-positive candidates: inspiration hits on MIT-licensed source where
    the bigrams are likely boilerplate patterns

Scope: this is calibration against registered references (currently seeded from
corpus/references/), NOT universal provenance across the internet. The guard
checks against what you've registered — nothing more.

Usage:
    python scripts/pb_provenance_calibrate.py
    python scripts/pb_provenance_calibrate.py --locked-dir corpus/programbench/locked
    python scripts/pb_provenance_calibrate.py --top-bigrams 30 --min-tier inspiration
    python scripts/pb_provenance_calibrate.py --json-out logs/provenance_calibrate.json
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from collections import Counter
from pathlib import Path

# Ensure scripts/ is on the path when run from repo root
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from determinex_copyright_guard import (  # noqa: E402
    CopyrightGuard,
    _filtered_bigrams,
    _license_tier,
    _tokenize,
    get_guard,
)


def _extract_source_from_tarball(tarball: Path) -> str | None:
    """Return text of source/main.py (or compile.sh) from a submission tarball."""
    try:
        with tarfile.open(tarball, "r:gz") as tf:
            names = tf.getnames()
            # Prefer source/main.py, then compile.sh
            for candidate in ("source/main.py", "compile.sh", "source/compile.sh"):
                if candidate in names:
                    member = tf.getmember(candidate)
                    with tf.extractfile(member) as fh:  # type: ignore[arg-type]
                        return fh.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    return None


def _read_source_file(tool_dir: Path) -> str | None:
    """Read source text from a locked tool directory."""
    # Prefer source/main.py in the directory
    for candidate in [
        tool_dir / "source" / "main.py",
        tool_dir / "source" / "compile.sh",
        tool_dir / "compile.sh",
    ]:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="replace")

    # Fall back to extracting from submission.tar.gz
    tarball = tool_dir / "submission.tar.gz"
    if tarball.exists():
        return _extract_source_from_tarball(tarball)

    return None


def calibrate(
    locked_dir: Path,
    guard: CopyrightGuard,
    top_bigrams: int = 20,
    min_tier: str = "inspiration",
) -> dict:
    """
    Walk locked_dir, run check_provenance on each tool, collect stats.
    Returns a dict suitable for JSON serialization or human display.
    """
    tier_order = {"verbatim_reproduction": 0, "substantial_similarity": 1, "inspiration": 2}
    min_tier_idx = tier_order.get(min_tier, 2)

    tools_scanned = 0
    tools_with_tags: set[str] = set()
    tier_counts: Counter[str] = Counter()
    source_hit_counts: Counter[str] = Counter()
    source_license_tiers: dict[str, str] = {}
    false_positive_candidates: list[dict] = []
    # bigrams that appear in false-positive inspiration hits
    fp_bigram_counter: Counter[tuple[str, str]] = Counter()

    tool_dirs = sorted(p for p in locked_dir.iterdir() if p.is_dir())

    for tool_dir in tool_dirs:
        tool_name = tool_dir.name
        source = _read_source_file(tool_dir)
        if source is None:
            continue

        tools_scanned += 1
        report = guard.check_provenance(source, task_id=f"calibrate_{tool_name}")

        if report.has_attributions:
            tools_with_tags.add(tool_name)

        for tag in report.attribution_tags:
            tier_idx = tier_order.get(tag.match_type, 99)
            if tier_idx > min_tier_idx:
                continue
            tier_counts[tag.match_type] += 1
            source_hit_counts[tag.source_label] += 1
            source_license_tiers[tag.source_label] = _license_tier(tag.license)

            # Flag inspiration-tier hits on permissive sources as FP candidates
            if tag.match_type == "inspiration" and _license_tier(tag.license) == "permissive":
                out_tokens = _tokenize(source)
                fbg = _filtered_bigrams(out_tokens)
                # Find the bigrams that drove the Jaccard score (present in both)
                ref_refs = [r for r in guard._references if r.label == tag.source_label]
                if ref_refs:
                    ref_fbg = ref_refs[0].filtered_bigrams
                    shared = fbg & ref_fbg
                    fp_bigram_counter.update(shared)

                false_positive_candidates.append(
                    {
                        "tool": tool_name,
                        "source": tag.source_label,
                        "license": tag.license,
                        "similarity": round(tag.similarity_score, 4),
                        "excerpt": tag.excerpt[:120],
                    }
                )

    # Build summary
    summary = {
        "tools_scanned": tools_scanned,
        "tools_with_any_tag": len(tools_with_tags),
        "tag_rate_pct": round(len(tools_with_tags) / max(tools_scanned, 1) * 100, 1),
        "tier_counts": dict(tier_counts),
        "source_hit_counts": dict(source_hit_counts.most_common()),
        "source_license_tiers": source_license_tiers,
        "fp_candidates_count": len(false_positive_candidates),
        "top_fp_bigrams": [
            {"bigram": list(bg), "count": cnt}
            for bg, cnt in fp_bigram_counter.most_common(top_bigrams)
        ],
        "fp_candidates": false_positive_candidates[:50],
    }
    return summary


def _print_report(summary: dict) -> None:
    print(f"\n{'─' * 60}")
    print("  Provenance Calibration Report")
    print(f"{'─' * 60}")
    print(f"  Tools scanned:          {summary['tools_scanned']}")
    print(
        f"  Tools with any tag:     {summary['tools_with_any_tag']}  ({summary['tag_rate_pct']}%)"
    )
    print()
    print("  Tags by tier:")
    for tier, count in sorted(summary["tier_counts"].items()):
        print(f"    {tier:<30} {count}")
    print()
    print("  Hits by reference source:")
    for label, count in list(summary["source_hit_counts"].items())[:15]:
        tier = summary["source_license_tiers"].get(label, "unknown")
        print(f"    [{tier:<11}]  {count:>4}×  {label}")
    print()
    print(f"  Inspiration FP candidates:  {summary['fp_candidates_count']}")
    if summary["top_fp_bigrams"]:
        print("  Top shared bigrams in FP inspiration hits (stoplist candidates):")
        for entry in summary["top_fp_bigrams"][:15]:
            bg = " ".join(entry["bigram"])
            print(f"    {entry['count']:>4}×  {bg}")
    print(f"{'─' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--locked-dir",
        default="corpus/programbench/locked",
        help="Directory containing locked tool subdirectories",
    )
    parser.add_argument(
        "--top-bigrams",
        type=int,
        default=20,
        help="Number of top false-positive bigrams to show",
    )
    parser.add_argument(
        "--min-tier",
        choices=["verbatim_reproduction", "substantial_similarity", "inspiration"],
        default="inspiration",
        help="Minimum match tier to include in analysis",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="Write full JSON summary to this path",
    )
    args = parser.parse_args()

    locked_dir = Path(args.locked_dir)
    if not locked_dir.exists():
        print(f"[calibrate] locked-dir not found: {locked_dir}", file=sys.stderr)
        sys.exit(1)

    guard = get_guard()
    if not guard._references:
        print(
            "[calibrate] WARNING: no reference sources registered — nothing to calibrate against."
        )
        print("  Seed corpus/references/ first (see corpus/references/README.md).")
        sys.exit(0)

    print(
        f"[calibrate] scanning {locked_dir} against {len(guard._references)} registered references..."
    )
    summary = calibrate(locked_dir, guard, top_bigrams=args.top_bigrams, min_tier=args.min_tier)
    _print_report(summary)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[calibrate] JSON summary written to {out_path}")


if __name__ == "__main__":
    main()
