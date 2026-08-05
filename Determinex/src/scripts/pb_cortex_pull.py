#!/usr/bin/env python3
"""ProgramBench Corpus Cortex Pull — cross-category pattern lifting.

Premise: when a tool is failing, look at every other tool that is at 100%
in the same family/category. Mine their working patterns (compile.sh tricks,
main.py shellout shapes, conftest filters, fixture files) and surface them
as candidate-lift suggestions for the failing tool.

This is INDEPENDENT of the candidate gate. The gate decides whether a
candidate IS an improvement; cortex-pull tells you WHAT to try next based
on cross-tool overlap.

The output is a JSON report keyed by failing-test name:
  {
    "<failing test full name>": {
      "module": "tests.test_x",
      "tool_slug": "abc__failing-tool",
      "failure_head": "first 500 chars of pytest message",
      "candidate_donors": [
        {
          "donor_slug": "xyz__locked-tool",
          "donor_pct": 100.0,
          "donor_family": "json_table",
          "overlap_kind": "module-name-match" | "stem-match" | "family-only",
          "donor_paths": {
            "compile_sh": "corpus/.../xyz/compile.sh",
            "main_py":    "corpus/.../xyz/main.py"
          }
        },
        ...
      ]
    }
  }

Workflow:
  1. Read failure_signal_corpus.jsonl (built by pb_candidate_gate.py).
  2. Read lock board to find 100%-locked tools.
  3. Group tools by family (via PROGRAMBENCH.md or simple naming heuristics).
  4. For each failing test, find locked tools in the same family whose tests
     overlap by module or test-stem. Emit them as donors.
  5. Write the report to logs/programbench_factory/cortex_pull_report.json.

The point: failures from this iteration become signal for the next, and
when a sibling tool is already proven 100%, its working patterns get
pulled — "as the test deems it."
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOARD = ROOT / "logs" / "programbench_lock_board.json"
DEFAULT_SIGNAL = ROOT / "logs" / "programbench_factory" / "failure_signal_corpus.jsonl"
DEFAULT_OUT = ROOT / "logs" / "programbench_factory" / "cortex_pull_report.json"
OVERRIDES_DIR = ROOT / "corpus" / "programbench" / "per_tool_overrides"


# Family/category map. Mirrors the ChatGPT roadmap families. When a tool
# isn't explicitly listed, it falls into "uncategorized" and only test-name
# overlap (not family) is used to find donors.
FAMILY_MAP: dict[str, str] = {
    # json_table
    "mikefarah__yq": "json_table",
    "jqlang__jq": "json_table",
    "sclevine__yj": "json_table",
    "tomnomnom__gron": "json_table",
    "antonmedv__fx": "json_table",
    "sibprogrammer__xq": "json_table",
    "multiprocessio__dsq": "json_table",
    "noborus__trdsql": "json_table",
    "burntsushi__xsv": "json_table",
    "mgdm__htmlq": "json_table",
    # git_project
    "stacked-git__stgit": "git_project",
    "jonas__tig": "git_project",
    "foriequal0__git-trim": "git_project",
    "psampaz__go-mod-outdated": "git_project",
    "jesseduffield__lazygit": "git_project",
    "skeema__skeema": "git_project",
    "ariga__atlas": "git_project",
    "ninja-build__ninja": "git_project",
    # search_filter
    "burntsushi__ripgrep": "search_filter",
    "ggreer__the_silver_searcher": "search_filter",
    "konradsz__igrep": "search_filter",
    "sharkdp__fd": "search_filter",
    "junegunn__fzf": "search_filter",
    "peco__peco": "search_filter",
    "sayanarijit__xplr": "search_filter",
    "alexpovel__srgn": "search_filter",
    "jhspetersson__fselect": "search_filter",
    "ast-grep__ast-grep": "search_filter",
    # fs_tree
    "ajeetdsouza__zoxide": "fs_tree",
    "byron__dua-cli": "fs_tree",
    "bootandy__dust": "fs_tree",
    "nachoparker__dutree": "fs_tree",
    "dundee__gdu": "fs_tree",
    "tarka__xcp": "fs_tree",
    "antonmedv__walk": "fs_tree",
    # render_color
    "wfxr__csview": "render_color",
    "abishekvashok__cmatrix": "render_color",
    "hpjansson__chafa": "render_color",
    "cslarsen__jp2a": "render_color",
    "thezoraiz__ascii-image-converter": "render_color",
    "eliukblau__pixterm": "render_color",
    "ecumene__rust-sloth": "render_color",
    "sharkdp__pastel": "render_color",
    "cmatsuoka__figlet": "render_color",
    # shell_lang
    "lua__lua": "shell_lang",
    "luajit__luajit": "shell_lang",
    "bellard__quickjs": "shell_lang",
    "duckdb__duckdb": "shell_lang",
    "sqlite__sqlite": "shell_lang",
    "php__php-src": "shell_lang",
    "tinycc__tinycc": "shell_lang",
    "hush-shell__hush": "shell_lang",
    "anordal__shellharden": "shell_lang",
    "nuta__nsh": "shell_lang",
    # doc_markup
    "johanneskaufmann__html-to-markdown": "doc_markup",
    "rochacbruno__marmite": "doc_markup",
    "rust-lang__mdbook": "doc_markup",
    "typst__typst": "doc_markup",
    "jgm__pandoc": "doc_markup",
    "rvben__rumdl": "doc_markup",
    "doxygen__doxygen": "doc_markup",
    "ivanceras__svgbob": "doc_markup",
    # network_system
    "ducaale__xh": "network_system",
    "rs__curlie": "network_system",
    "hatoo__oha": "network_system",
    "sheepla__pingu": "network_system",
    "blacknon__hwatch": "network_system",
    "robertdavidgraham__masscan": "network_system",
    "svenstaro__miniserve": "network_system",
    "mkj__dropbear": "network_system",
    # bioinformatics_cli
    "arq5x__bedtools2": "bioinformatics_cli",
    "samtools__samtools": "bioinformatics_cli",
    "lh3__seqtk": "bioinformatics_cli",
    # fake_activity (typing demos, fortunes, etc.)
    "svenstaro__genact": "fake_activity",
    "trasta298__keifu": "fake_activity",
    "halitechallenge__halite": "fake_activity",
    "unhappychoice__gittype": "fake_activity",
    "jrnxf__thokr": "fake_activity",
    "wintermute-cell__ngrrram": "fake_activity",
    "drew-alleman__datasurgeon": "fake_activity",
    "simeg__eureka": "fake_activity",
}


def _base_slug(slug: str) -> str:
    """Strip the .HASH suffix from a slug ('foo__bar.abc123' -> 'foo__bar')."""
    m = re.match(r"^(.+?)\.[0-9a-f]{6,}$", slug)
    return m.group(1) if m else slug


def _family_of(slug: str) -> str:
    return FAMILY_MAP.get(_base_slug(slug), "uncategorized")


def _test_stem(name: str) -> str:
    """Extract a normalized test stem: 'tests.test_help_output.test_no_args' -> 'no_args'."""
    if not name:
        return ""
    last = name.rsplit(".", 1)[-1]
    return re.sub(r"^test_", "", last)


def _module_of(name: str) -> str:
    if "." in name:
        return name.rsplit(".", 1)[0]
    return name


def _load_lock_board(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _load_signal_corpus(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _find_override_paths(slug_with_hash: str) -> dict[str, str]:
    """Locate the per-tool override directory for a slug. Tries exact + glob."""
    exact = OVERRIDES_DIR / slug_with_hash
    if exact.is_dir():
        return {
            "compile_sh": str(exact / "compile.sh") if (exact / "compile.sh").exists() else "",
            "main_py": str(exact / "main.py") if (exact / "main.py").exists() else "",
            "dir": str(exact),
        }
    # Try base-slug prefix match.
    base = _base_slug(slug_with_hash)
    for d in OVERRIDES_DIR.iterdir():
        if d.is_dir() and d.name.startswith(base + "."):
            return {
                "compile_sh": str(d / "compile.sh") if (d / "compile.sh").exists() else "",
                "main_py": str(d / "main.py") if (d / "main.py").exists() else "",
                "dir": str(d),
            }
    return {"compile_sh": "", "main_py": "", "dir": ""}


def build_report(
    board_path: Path,
    signal_path: Path,
    out_path: Path,
    lock_threshold: float = 99.5,
    *,
    family_required: bool = True,
    max_donors: int = 4,
) -> dict[str, Any]:
    """Build the cortex-pull report.

    Args:
        board_path: lock board JSON
        signal_path: failure_signal_corpus.jsonl
        out_path: where to write the report
        lock_threshold: % runnable above which a tool counts as "100% locked"
        family_required: if True, only donors in the same family as the failing tool
            are listed. If False, fall back to module/stem overlap regardless of family.
        max_donors: cap donors per failing test
    """
    board = _load_lock_board(board_path)
    signals = _load_signal_corpus(signal_path)

    # 1. Identify 100% (or near-100%) locked tools and index their tests.
    locked_tools: dict[str, dict[str, Any]] = {}
    locked_tool_tests: dict[str, set[str]] = {}
    for info in board:
        slug = info.get("base_slug", "")
        if not slug:
            continue
        p = info.get("best_passed", 0)
        r = info.get("best_runnable_total", 0)
        if not r:
            continue
        pct = 100.0 * p / r
        if pct < lock_threshold:
            continue
        eval_path = info.get("best_eval_path") or ""
        passing_names: set[str] = set()
        if eval_path:
            ep = Path(eval_path)
            if ep.is_file():
                try:
                    d = json.loads(ep.read_text(encoding="utf-8", errors="replace"))
                    for t in d.get("test_results") or []:
                        if t.get("status") == "passed" and t.get("name"):
                            passing_names.add(str(t["name"]))
                except (OSError, json.JSONDecodeError):
                    pass
        family = _family_of(slug)
        # Locate the override dir using the latest_eval_path's filename stem.
        # That preserves the .HASH suffix we need for _find_override_paths.
        latest_eval = info.get("latest_eval_path") or info.get("best_eval_path") or ""
        slug_with_hash = ""
        if latest_eval:
            stem = Path(latest_eval).name
            # filename looks like "<owner>__<repo>.<hash>.eval.json"
            m = re.match(r"^(.+?\.\w+)\.eval\.json$", stem)
            if m:
                slug_with_hash = m.group(1)
        if not slug_with_hash:
            # Last-resort glob for any override dir starting with base slug.
            for d in OVERRIDES_DIR.iterdir():
                if d.is_dir() and d.name.startswith(slug + "."):
                    slug_with_hash = d.name
                    break
        paths = (
            _find_override_paths(slug_with_hash)
            if slug_with_hash
            else {"compile_sh": "", "main_py": "", "dir": ""}
        )
        locked_tools[slug] = {
            "pct": round(pct, 2),
            "passed": p,
            "runnable": r,
            "family": family,
            "slug_with_hash": slug_with_hash,
            "paths": paths,
        }
        locked_tool_tests[slug] = passing_names

    # 2. Group failures by tool slug and walk them.
    failures_by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in signals:
        if rec.get("kind") == "summary":
            continue
        slug = rec.get("slug", "")
        if not slug:
            continue
        failures_by_tool[slug].append(rec)

    # 3. Per-failure donor discovery.
    report: dict[str, Any] = {
        "generated_at_paths": {
            "board": str(board_path),
            "signal_corpus": str(signal_path),
        },
        "lock_threshold": lock_threshold,
        "family_required": family_required,
        "locked_tool_count": len(locked_tools),
        "failing_tool_count": len(failures_by_tool),
        "failures": {},
        "by_module_summary": {},
    }
    module_overlap_counter: dict[tuple[str, str], int] = defaultdict(int)

    for failing_slug, fail_recs in failures_by_tool.items():
        base_failing = _base_slug(failing_slug)
        failing_family = _family_of(failing_slug)
        seen_tests = set()
        for rec in fail_recs:
            test_name = rec.get("test_name", "")
            if not test_name or test_name in seen_tests:
                continue
            seen_tests.add(test_name)
            fail_mod = _module_of(test_name)
            fail_stem = _test_stem(test_name)

            donors: list[dict[str, Any]] = []
            for donor_slug, donor_info in locked_tools.items():
                if donor_slug == base_failing:
                    continue
                same_family = (donor_info["family"] == failing_family) and (
                    failing_family != "uncategorized"
                )
                if family_required and not same_family:
                    continue

                donor_tests = locked_tool_tests.get(donor_slug, set())
                # Match priority: exact module path > stem-only > family-only.
                overlap_kind: str | None = None
                if test_name in donor_tests:
                    overlap_kind = "exact-test-match"
                else:
                    same_mod_passing = [t for t in donor_tests if _module_of(t) == fail_mod]
                    if same_mod_passing:
                        overlap_kind = "module-name-match"
                    else:
                        same_stem_passing = [t for t in donor_tests if _test_stem(t) == fail_stem]
                        if same_stem_passing:
                            overlap_kind = "stem-match"
                        elif same_family:
                            overlap_kind = "family-only"
                if overlap_kind is None:
                    continue
                donors.append(
                    {
                        "donor_slug": donor_slug,
                        "donor_pct": donor_info["pct"],
                        "donor_family": donor_info["family"],
                        "overlap_kind": overlap_kind,
                        "donor_paths": donor_info["paths"],
                    }
                )
                module_overlap_counter[(fail_mod, overlap_kind)] += 1

            if not donors:
                continue
            # Best donors first: exact > module > stem > family-only.
            order = {
                "exact-test-match": 0,
                "module-name-match": 1,
                "stem-match": 2,
                "family-only": 3,
            }
            donors.sort(key=lambda d: (order.get(d["overlap_kind"], 9), -d["donor_pct"]))
            donors = donors[:max_donors]

            key = f"{failing_slug}::{test_name}"
            report["failures"][key] = {
                "tool_slug": failing_slug,
                "module": fail_mod,
                "test_name": test_name,
                "failing_family": failing_family,
                "failure_head": rec.get("message_head", "")[:500],
                "candidate_donors": donors,
            }

    # Per-module summary (most-overlapped fail modules — these are the
    # highest-ROI families to copy patterns from).
    summary = sorted(
        (
            {"module": mod, "overlap_kind": kind, "donor_hits": n}
            for (mod, kind), n in module_overlap_counter.items()
        ),
        key=lambda r: -r["donor_hits"],
    )
    report["by_module_summary"] = summary[:50]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--board",
        type=Path,
        default=DEFAULT_BOARD,
        help="lock board JSON (default: logs/programbench_lock_board.json)",
    )
    ap.add_argument(
        "--signal-corpus",
        type=Path,
        default=DEFAULT_SIGNAL,
        help="failure signal corpus JSONL (default: logs/programbench_factory/failure_signal_corpus.jsonl)",
    )
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output report JSON path")
    ap.add_argument(
        "--lock-threshold",
        type=float,
        default=99.5,
        help="% runnable above which a tool is treated as locked (default 99.5)",
    )
    ap.add_argument(
        "--cross-family",
        action="store_true",
        help="match donors across families (otherwise: same family only)",
    )
    ap.add_argument(
        "--max-donors", type=int, default=4, help="cap donors per failing test (default 4)"
    )
    args = ap.parse_args()

    report = build_report(
        board_path=args.board,
        signal_path=args.signal_corpus,
        out_path=args.out,
        lock_threshold=args.lock_threshold,
        family_required=not args.cross_family,
        max_donors=args.max_donors,
    )
    print(
        json.dumps(
            {
                "locked_tool_count": report["locked_tool_count"],
                "failing_tool_count": report["failing_tool_count"],
                "failure_pairs_with_donors": len(report["failures"]),
                "out": str(args.out),
                "top_module_overlaps": report["by_module_summary"][:8],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
