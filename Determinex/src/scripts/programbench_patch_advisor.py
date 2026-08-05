"""scripts/programbench_patch_advisor.py — universal-patch recommender.

Given a live monitor snapshot, the advisor:

  1. Identifies the dominant cross-batch failure family.
  2. Looks up the matching universal patch in its profile library.
  3. Computes a confidence score (how concentrated is this family? how
     consistent are the failures? how many other families are in flight?).
  4. Estimates expected impact (best-case if the patch resolves the whole
     family on every affected tool — that's the upper bound).
  5. Returns a structured recommendation the frontend / human can act on.

Architecture: a small generic core plus pluggable profiles. ProgramBench
ships first; SWE-bench / Rosetta / micro-eval profiles slot into the same
shape later. A profile is just a list of UniversalPatch rules:

    UniversalPatch(
        family="rc_2_unknown_option",
        title="Use clap-style 'error: unexpected argument' wording, exit 1",
        rationale="...",
        scaffold_changes=[CodeChange(file=..., before=..., after=..., why=...)],
        validation=["micro:unknown-flag", "shard:5-tools"],
        expected_impact_pp=8.0,
        confidence=0.85,
        tags=["clap", "rust-clone-tools"],
    )

The advisor does NOT apply patches; it only proposes them. The three-speed
eval gate (micro → shard → full) gets the final say.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Generic core
# ---------------------------------------------------------------------------


@dataclass
class CodeChange:
    """One concrete edit a patch needs in the scaffold template."""

    file: str
    locator: str  # "function: parse_args" or "regex: <pattern>"
    before: str  # what the code currently looks like (snippet)
    after: str  # what it should look like (snippet)
    why: str  # one-line rationale


@dataclass
class UniversalPatch:
    """A profile rule — maps a failure family to a concrete scaffold change."""

    family: str
    title: str
    rationale: str
    scaffold_changes: list[CodeChange] = field(default_factory=list)
    validation: list[str] = field(default_factory=list)  # ["micro:...", "shard:..."]
    expected_impact_pp: float = 0.0  # upper-bound % points lift
    confidence: float = 0.5  # 0..1
    tags: list[str] = field(default_factory=list)
    # Status hooks for the cockpit:
    history: list[str] = field(default_factory=list)  # e.g. ["staged 2026-05-13"]
    # Literal substrings the patch's output should produce. The advisor scans
    # failing-test expected-output strings for these to compute the
    # assertion-string overlap signal — the cheap correction for the iter-1
    # finding that family share alone over-predicts patchability.
    literal_match_strings: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    """What the advisor returns. JSON-serializable for the frontend."""

    rank: int
    family: str
    patch: UniversalPatch
    family_failures: int
    family_tools_affected: int
    family_share_of_failures: float  # 0..1
    family_share_of_tools: float  # 0..1
    estimated_lift_pp: float  # tempered by confidence and concentration
    confidence_label: str  # "high" | "medium" | "low"
    # Iter-1 lesson signals — set when eval_json_paths is supplied to propose().
    assertion_string_overlap: float | None = None  # 0..1; None = not computed
    overlap_sample_size: int = 0  # how many failing tests scanned
    confidence_adjustment: str = "none"  # "none" | "penalty_low_overlap"

    def to_dict(self) -> dict:
        d = asdict(self)
        # Inline patch (dataclass nested dump)
        d["patch"] = asdict(self.patch)
        d["patch"]["scaffold_changes"] = [asdict(c) for c in self.patch.scaffold_changes]
        return d


# ---------------------------------------------------------------------------
# ProgramBench profile — encodes the 8 universal CLI patterns
# ---------------------------------------------------------------------------

PROGRAMBENCH_PROFILE: dict[str, UniversalPatch] = {
    "rc_2_unknown_option": UniversalPatch(
        family="rc_2_unknown_option",
        title="Clap-style 'error: unexpected argument' wording + exit 1",
        rationale=(
            "Tests grep stderr for 'unexpected argument' or 'unrecognized'; "
            "many also assert returncode == 1, not 2. Our scaffold emitted "
            "'<tool>: unknown option:' and exited 2. Adopting clap-2 wording "
            "covers the majority of these failures."
        ),
        scaffold_changes=[
            CodeChange(
                file="scripts/mass_run_v2_scaffold.py",
                locator="PYTHON_TEMPLATE: parse_args, both unknown-flag branches",
                # before/after are LITERAL template text (double-brace escapes
                # for {{TOOL_NAME}} / {{a}}). The patch applier compares against
                # the template file as-shipped, not the rendered output.
                before='eprint(f"{{TOOL_NAME}}: unknown option: {{a}}")\n                sys.exit(2)',
                after=(
                    "eprint(f\"error: unexpected argument '{{a}}' found\")\n"
                    '                eprint("")\n'
                    '                eprint(f"Usage: {{TOOL_NAME}} [OPTIONS] [INPUT...]")\n'
                    '                eprint("")\n'
                    "                eprint(\"For more information, try '--help'.\")\n"
                    "                sys.exit(1)"
                ),
                why="match clap-2 error format used by most Rust upstream tools",
            ),
        ],
        validation=[
            "micro:unknown-flag-bare",
            "micro:unknown-flag-equals-form",
            "micro:help-still-rc0",
            "shard:5-rust-residuals",
        ],
        expected_impact_pp=8.0,
        confidence=0.85,
        tags=["clap", "tier-1", "universal", "iter-1", "low-universal-lift-evidence"],
        history=[
            "drafted 2026-05-13 from base run at 44/115; staged in scaffold but not applied to base",
            "iter-1 shard 2026-05-14: only 1/4 tools lifted (nomino +3.55pp; hyperfine/genact/direnv +0.00pp) — "
            "most rc_2_unknown_option failures actually require tool-specific app errors, not clap wording. "
            "Mark family as low-universal-lift; future picks must factor literal assertion-string overlap.",
        ],
        literal_match_strings=[
            "unexpected argument",  # clap-2 wording
            "unrecognized argument",  # argparse wording
        ],
    ),
    "help_text_mismatch": UniversalPatch(
        family="help_text_mismatch",
        title="Help text: 'Usage: <tool> [OPTIONS] [INPUT...]' first line, exit 0, stdout",
        rationale=(
            "test_help_* tests grep for 'usage:' in stdout and assert exit 0. "
            "Some tools want 'Usage:' (capitalized, clap-style), others want "
            "'usage:' (lowercase, argparse-style). The clap form covers more "
            "Rust-origin tools; the lowercase form covers more Python/Go-origin."
        ),
        scaffold_changes=[
            CodeChange(
                file="scripts/mass_run_v2_scaffold.py",
                locator="PYTHON_TEMPLATE: USAGE constant",
                before='USAGE = f"""usage: {{TOOL_NAME}} [OPTIONS] [INPUT...]',
                after='USAGE = f"""Usage: {{TOOL_NAME}} [OPTIONS] [INPUT...]',
                why="clap-2 capitalizes 'Usage:'; covers more Rust upstream tools",
            ),
        ],
        validation=["micro:help-stdout-rc0", "shard:5-tools"],
        expected_impact_pp=2.5,
        confidence=0.55,
        tags=[
            "help",
            "tier-1",
            "ambivalent-case",
            "needs-better-expected-extraction",
            "deferred-2026-05-14",
        ],
        literal_match_strings=["Usage:", "usage:"],
        history=[
            "probed 2026-05-14: of 6,702 help_text_mismatch failures, only 0.8% literally "
            "expect 'Usage:' (capitalized) and 66.4% scan as 'usage:' lowercase — but the "
            "actual expected wordings are tool-specific descriptions (e.g. 'Find the password "
            "of protected ZIP files'), not the Usage line itself. NOT a universal-patch family "
            "until advisor's overlap extraction handles `assert X in Y` properly and subtracts "
            "scaffold's own output from the message scan.",
        ],
    ),
    "file_not_found": UniversalPatch(
        family="file_not_found",
        title="File-not-found message: 'No such file or directory' (POSIX), exit 2",
        rationale=(
            "Most tools mirror POSIX errno wording 'No such file or directory'. "
            "Our scaffold already emits this, but some tools expect a leading "
            "'error:' and clap-style format. This patch tries both message "
            "shapes and chooses based on shard validation."
        ),
        scaffold_changes=[
            CodeChange(
                file="scripts/mass_run_v2_scaffold.py",
                locator="PYTHON_TEMPLATE: process_file function",
                before="eprint(f\"{{TOOL_NAME}}: cannot access '{{path}}': No such file or directory\")",
                after=(
                    "eprint(f\"error: failed to read '{{path}}'\")\n"
                    '        eprint(f"  caused by: No such file or directory (os error 2)")\n'
                ),
                why="Rust/anyhow-style error chain wording covers more tools than POSIX-only",
            ),
        ],
        validation=["micro:file-not-found-rc2", "shard:5-tools"],
        expected_impact_pp=1.8,
        confidence=0.45,
        tags=["file-io", "tier-2", "needs-better-expected-extraction", "deferred-2026-05-14"],
        literal_match_strings=[
            "No such file or directory",
            "cannot access",
            "os error 2",
        ],
        history=[
            "probed 2026-05-14: of 11,141 file_not_found failures, 98.9% have NO capturable "
            "expected wording — they're rc-check assertions (`assert returncode == N`), not "
            "wording asserts. The 100% overlap the advisor showed was inflated by whole-message "
            "scan (matching our scaffold's own POSIX output). NOT a universal-patch family "
            "until advisor extracts rc-expected vs wording-expected separately.",
        ],
    ),
    "version_format": UniversalPatch(
        family="version_format",
        title="Version output: '<tool> <version>' single line, stdout, exit 0",
        rationale=(
            "test_version_* asserts a single-line output of the form "
            "'<toolname> <version>'. Some tools include a 'v' prefix on the "
            "version, others don't. Our scaffold already does the bare form; "
            "this patch is more about confirming no extra whitespace/trailing "
            "newlines than a wording change."
        ),
        scaffold_changes=[],
        validation=["micro:version-stdout-rc0"],
        expected_impact_pp=0.6,
        confidence=0.3,
        tags=["version", "tier-1", "low-leverage"],
    ),
    "stdin_handling": UniversalPatch(
        family="stdin_handling",
        title="Stdin handling: bare invocation reads stdin when piped, errors on TTY",
        rationale=(
            "Tests assert that 'echo foo | <tool>' processes the stdin "
            "content. Our scaffold already does this via sys.stdin.isatty() "
            "check. Failures usually come from EXIT CODE on empty stdin (should "
            "be 0, sometimes 1) and whether the tool treats '-' as a stdin "
            "sentinel positional."
        ),
        scaffold_changes=[],
        validation=["micro:stdin-pipe-passthrough", "micro:stdin-empty-rc0"],
        expected_impact_pp=1.0,
        confidence=0.4,
        tags=["stdin", "tier-1"],
    ),
}


# ---------------------------------------------------------------------------
# Recommender
# ---------------------------------------------------------------------------

# Confidence penalty when literal-string overlap is low. Iter-1 lesson:
# family share is necessary but not sufficient. If <30% of failing tests in the
# target family literally expect the patch's wording, halve the confidence —
# the patch probably won't lift those tests no matter how dominant the family.
_OVERLAP_PENALTY_THRESHOLD = 0.30
_OVERLAP_PENALTY_FACTOR = 0.5


def _expected_text_from_message(msg: str) -> str:
    """Extract the EXPECTED side of a pytest assertion-error message.

    pytest writes failures like:
        AssertionError: assert 'actual\\n' == 'expected\\n'
            - 'expected\\n'
            + 'actual\\n'
    The expected text usually appears after ' == ' or on a '- ' prefixed
    line in the diff. Returning the full message as a fallback is safe;
    overlap is computed via substring containment so extra noise just
    dilutes the signal symmetrically across all candidate patches.
    """
    if not msg:
        return ""
    # Common pattern: "got: X" / "expected: Y" / pytest "==" / pytest diff line
    return msg  # full msg; substring scan handles noise


def compute_assertion_string_overlap(
    eval_json_paths: list[Path],
    *,
    family: str,
    literal_match_strings: list[str],
) -> tuple[float | None, int]:
    """Scan failing tests in the named family across eval JSONs.

    Returns (overlap_fraction, sample_size). overlap_fraction is the fraction
    of failing tests whose expected-output message literally contains AT LEAST
    ONE of the patch's `literal_match_strings`. Returns (None, 0) if no
    `literal_match_strings` provided or no failures matched the family.

    Used by propose() to penalize confidence when a high-family-share patch
    has low expected-output match (the iter-1 lesson — rc_2_unknown_option
    owned 59% of failures but only ~13% literally expected the clap wording).
    """
    if not literal_match_strings:
        return None, 0
    # Lazy import to avoid circular: classifier is in the same scripts/ dir.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from determinex_pb_taxonomy import classify_one  # type: ignore[import-not-found]

    sample = 0
    hits = 0
    for ej in eval_json_paths:
        try:
            d = json.loads(Path(ej).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for t in d.get("test_results", []) or []:
            if t.get("status") == "passed":
                continue
            msg = str(t.get("extra", {}).get("message", "")) or ""
            fam = classify_one(str(t.get("name", "")), msg)
            if fam != family:
                continue
            sample += 1
            txt = _expected_text_from_message(msg)
            if any(sub in txt for sub in literal_match_strings):
                hits += 1
    if sample == 0:
        return None, 0
    return round(hits / sample, 3), sample


def propose(
    snapshot: dict,
    profile: dict[str, UniversalPatch] = PROGRAMBENCH_PROFILE,
    top_k: int = 3,
    *,
    eval_json_paths: list[Path] | None = None,
) -> list[Recommendation]:
    """Rank patches for the snapshot's top failure families."""
    families = snapshot.get("top_families", [])
    if not families:
        return []
    total_failures = sum(f["failures"] for f in families) or 1
    total_tools = max((f["tools_affected"] for f in families), default=1)

    recs: list[Recommendation] = []
    rank = 0
    for f in families:
        fam_name = f["family"]
        patch = profile.get(fam_name)
        if patch is None:
            continue
        rank += 1
        share_fail = f["failures"] / total_failures
        share_tool = f["tools_affected"] / total_tools

        # Iter-1 lesson: weight literal assertion-string overlap. If the
        # snapshot includes pointers to eval JSONs, scan failing tests in this
        # family for literal occurrences of the patch's expected wording.
        overlap, n_sample = compute_assertion_string_overlap(
            eval_json_paths or [],
            family=fam_name,
            literal_match_strings=patch.literal_match_strings,
        )
        adj = "none"
        effective_conf = patch.confidence
        if overlap is not None and overlap < _OVERLAP_PENALTY_THRESHOLD:
            effective_conf = patch.confidence * _OVERLAP_PENALTY_FACTOR
            adj = "penalty_low_overlap"

        # Estimated lift: temper the upper-bound by (penalty-adjusted) confidence
        # and family concentration. Concentration boosts lift for families that
        # affect many tools.
        concentration = (share_fail + share_tool) / 2
        lift = round(patch.expected_impact_pp * effective_conf * (0.5 + concentration), 2)
        if effective_conf >= 0.7 and share_fail >= 0.30:
            label = "high"
        elif effective_conf >= 0.45:
            label = "medium"
        else:
            label = "low"
        recs.append(
            Recommendation(
                rank=rank,
                family=fam_name,
                patch=patch,
                family_failures=f["failures"],
                family_tools_affected=f["tools_affected"],
                family_share_of_failures=round(share_fail, 3),
                family_share_of_tools=round(share_tool, 3),
                estimated_lift_pp=lift,
                confidence_label=label,
                assertion_string_overlap=overlap,
                overlap_sample_size=n_sample,
                confidence_adjustment=adj,
            )
        )
        if len(recs) >= top_k:
            break
    return recs


def propose_top_patch(
    snapshot: dict, profile: dict[str, UniversalPatch] = PROGRAMBENCH_PROFILE
) -> dict:
    """Convenience: just the top single patch, as a dict. Used by the live monitor."""
    recs = propose(snapshot, profile=profile, top_k=1)
    return recs[0].to_dict() if recs else {"status": "no_patch_for_top_family"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _discover_eval_jsons(scaffold_root: Path | None) -> list[Path]:
    """Find all per-instance *.eval.json under a scaffold root for overlap scoring."""
    if scaffold_root is None or not scaffold_root.is_dir():
        return []
    return list(scaffold_root.glob("*/*.eval.json"))


def _cli():
    ap = argparse.ArgumentParser(description="ProgramBench universal-patch advisor")
    ap.add_argument("--run-id", default="mass_run_v2_base")
    ap.add_argument("--expected-total", type=int, default=115)
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument(
        "--scaffold-root",
        type=Path,
        default=None,
        help="output root (e.g. T:/determinex-programbench/mass_run_v2_base) "
        "to scan for *.eval.json — enables assertion-string overlap scoring",
    )
    ap.add_argument("--json", action="store_true", help="JSON output (default: human-readable)")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from programbench_live_monitor import snapshot as _snapshot  # type: ignore

    snap = _snapshot(args.run_id, expected_total=args.expected_total)
    eval_paths = _discover_eval_jsons(args.scaffold_root)
    recs = propose(snap, top_k=args.top_k, eval_json_paths=eval_paths)

    if args.json:
        print(
            json.dumps(
                {
                    "run_id": args.run_id,
                    "n_completed": snap["n_completed_tasks"],
                    "rolling_avg": snap["rolling_avg_score"],
                    "eval_jsons_scanned": len(eval_paths),
                    "recommendations": [r.to_dict() for r in recs],
                },
                indent=2,
                default=str,
            )
        )
        return

    print(f"=== Patch advisor for {args.run_id} ===")
    print(
        f"  {snap['n_completed_tasks']} tasks completed, rolling avg {snap['rolling_avg_score']}/100"
    )
    if eval_paths:
        print(f"  scanning {len(eval_paths)} eval JSONs for assertion-string overlap")
    print()
    if not recs:
        print("  No patches recommended (no profile entry for the dominant families).")
        return
    for r in recs:
        print(f"  #{r.rank}  {r.patch.title}")
        print(
            f"        family:           {r.family}  ({r.family_failures:,} failures, {r.family_tools_affected} tools)"
        )
        print(
            f"        share:            {r.family_share_of_failures:.0%} of failures, {r.family_share_of_tools:.0%} of tools affected"
        )
        if r.assertion_string_overlap is not None:
            print(
                f"        string overlap:   {r.assertion_string_overlap:.0%} of {r.overlap_sample_size:,} failing tests "
                f"literally expect the patch wording  [{r.confidence_adjustment}]"
            )
        print(
            f"        confidence:       {r.confidence_label}  (raw {r.patch.confidence:.2f}{', adjusted' if r.confidence_adjustment != 'none' else ''})"
        )
        print(
            f"        estimated lift:   +{r.estimated_lift_pp} pp  (upper bound {r.patch.expected_impact_pp} pp)"
        )
        print(f"        rationale:        {r.patch.rationale[:120]}...")
        print(f"        validation gate:  {', '.join(r.patch.validation)}")
        if r.patch.scaffold_changes:
            print(f"        changes ({len(r.patch.scaffold_changes)}):")
            for c in r.patch.scaffold_changes:
                print(f"          - {c.file}  ::  {c.locator}")
        print()


if __name__ == "__main__":
    _cli()
