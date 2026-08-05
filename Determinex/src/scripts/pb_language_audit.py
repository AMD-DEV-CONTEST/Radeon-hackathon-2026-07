#!/usr/bin/env python3
"""ProgramBench language-routing audit.

For every per-tool override, determines:
  - What the tool's source language actually is (from classifier + slug map)
  - What language the current implementation lives in (main.py vs main.go
    vs main.rs vs main.c vs main.cpp etc.)
  - Whether main.py is a thin exec-wrapper around a bundled native binary,
    or contains substantive implementation logic
  - The action required: rewrite-in-native / keep-thin / keep-python

Output:
  docs/PROGRAMBENCH_LANGUAGE_AUDIT.md       human-readable table
  logs/programbench_factory/LANGUAGE_AUDIT.json  per-tool record

Run:
    python scripts/pb_language_audit.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES_DIR = ROOT / "corpus" / "programbench" / "per_tool_overrides"
LOCKED_DIR = ROOT / "corpus" / "programbench" / "locked"
BOARD_JSON = ROOT / "logs" / "programbench_lock_board.json"
CLASSIFIER_JSON = ROOT / "logs" / "programbench_factory" / "LANGUAGE_CLASSIFICATION.json"
OUT_JSON = ROOT / "logs" / "programbench_factory" / "LANGUAGE_AUDIT.json"
OUT_MD = ROOT / "docs" / "PROGRAMBENCH_LANGUAGE_AUDIT.md"

# Substantive-vs-thin threshold: lines of Python (excluding blank/comment)
THIN_PY_LINES = 30

# How big is a wrapper-only main.py? Anything that does more than
# exec/find-binary deserves to be flagged as substantive.
THIN_WRAPPER_FINGERPRINTS = (
    "subprocess.run",
    "os.execv",
    "shutil.which",
)


def _load_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_native_binary(p: Path) -> str | None:
    """Return a brief description if `p` looks like a native compiled binary."""
    try:
        with open(p, "rb") as f:
            head = f.read(8)
    except OSError:
        return None
    if head.startswith(b"\x7fELF"):
        return "ELF"
    if head[:2] == b"MZ":
        return "PE"
    if head[:4] in (
        b"\xfe\xed\xfa\xce",
        b"\xfe\xed\xfa\xcf",
        b"\xce\xfa\xed\xfe",
        b"\xcf\xfa\xed\xfe",
    ):
        return "Mach-O"
    return None


def _count_substantive_py_lines(text: str) -> int:
    n = 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        # docstrings - rough heuristic
        if s.startswith('"""') and s.endswith('"""') and len(s) > 6:
            continue
        n += 1
    return n


def _classify_main_py(path: Path) -> dict[str, Any]:
    """Tag main.py as thin-wrapper / substantive / scaffold-only."""
    if not path.is_file():
        return {"present": False}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"present": True, "unreadable": True}
    substantive = _count_substantive_py_lines(text)
    has_subprocess = any(fp in text for fp in THIN_WRAPPER_FINGERPRINTS)
    # Detect "scaffold" stubs that just print TOOL_NAME/USAGE/HELP and exit
    scaffold_markers = (
        "Universal patch #1: SIGPIPE handler",
        "bootstrap scaffold",
        "Determinex scaffold",
    )
    is_scaffold = any(m in text for m in scaffold_markers)
    # Thin wrapper: small file + has subprocess.run/execv + no big functions
    has_real_logic = bool(re.search(r"\bdef\s+\w+\s*\([^)]*\)\s*:", text))
    def_count = len(re.findall(r"\bdef\s+\w+", text))
    return {
        "present": True,
        "lines_substantive": substantive,
        "lines_total": len(text.splitlines()),
        "has_subprocess_exec": has_subprocess,
        "is_scaffold": is_scaffold,
        "def_count": def_count,
        "thin_wrapper": substantive <= THIN_PY_LINES or (def_count <= 2 and has_subprocess),
    }


def _detect_source_language(slug: str, lang_entry: dict[str, Any] | None) -> str:
    base = slug.split(".", 1)[0]
    # Verified local/known mapping beats classifier heuristics. The classifier
    # can mis-label slugs from owner/name alone (for example nuta__nsh is a
    # Rust crate despite earlier notes calling it C).
    known = {
        "burntsushi__ripgrep": "rust",
        "burntsushi__xsv": "rust",
        "sharkdp__fd": "rust",
        "sharkdp__hexyl": "rust",
        "sharkdp__pastel": "rust",
        "bootandy__dust": "rust",
        "byron__dua-cli": "rust",
        "chmln__sd": "rust",
        "pemistahl__grex": "rust",
        "mookid__diffr": "rust",
        "sstadick__hck": "rust",
        "kyoh86__richgo": "go",
        "sclevine__yj": "go",
        "tomnomnom__gron": "go",
        "konradsz__igrep": "rust",
        "rs__curlie": "go",
        "dundee__gdu": "go",
        "junegunn__fzf": "go",
        "peco__peco": "go",
        "ariga__atlas": "go",
        "sibprogrammer__xq": "go",
        "ogham__dog": "rust",
        "miserlou__loop": "rust",
        "raviqqe__muffet": "go",
        "trasta298__keifu": "rust",
        "psampaz__go-mod-outdated": "go",
        "jqlang__jq": "c",
        "lua__lua": "c",
        "tinycc__tinycc": "c",
        "sqlite__sqlite": "c",
        "nuta__nsh": "rust",
        "oppiliappan__eva": "python",
        "dalance__amber": "python",
        "abishekvashok__cmatrix": "c",
        "ajeetdsouza__zoxide": "rust",
        "anordal__shellharden": "rust",
        "mgdm__htmlq": "rust",
        "mikefarah__yq": "go",
        "orf__gping": "rust",
        "sirwart__ripsecrets": "rust",
        "wfxr__csview": "rust",
    }
    if base in known:
        return known[base]
    if lang_entry:
        lang = lang_entry.get("source_language")
        if lang and lang != "unknown":
            return lang
    return "unknown"


def _find_native_source(d: Path, language: str) -> list[Path]:
    """List native-source files of the expected language present in dir."""
    if language == "go":
        return sorted({p for p in d.glob("**/*.go")})
    if language == "rust":
        return sorted({p for p in d.glob("**/*.rs")})
    if language == "c":
        return sorted({p for p in d.glob("**/*.c")})
    if language == "cpp":
        return sorted({p for p in d.glob("**/*.cpp")})
    if language == "python":
        return []  # main.py IS the implementation; nothing extra needed
    return []


def _find_bundled_binary(d: Path, slug: str) -> dict[str, Any] | None:
    base = slug.split("__", 1)[-1].split(".")[0]
    candidates = list(d.iterdir())
    for f in candidates:
        if not f.is_file():
            continue
        if f.suffix in (".py", ".sh", ".pre_bundle", ".toml", ".mod", ".sum"):
            continue
        if f.name.startswith("."):
            continue
        if f.name in ("compile.sh", "main.py", "Cargo.toml", "go.mod", "go.sum"):
            continue
        bk = _is_native_binary(f)
        if bk:
            return {"name": f.name, "kind": bk, "size": f.stat().st_size}
    return None


def _read_compile_sh(d: Path) -> str:
    p = d / "compile.sh"
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _route_action(
    *,
    language: str,
    main_py: dict[str, Any],
    native_sources: list[Path],
    bundled_binary: dict[str, Any] | None,
    classification: str,
    score: float,
    locked: bool,
) -> tuple[str, str]:
    """Decide the action: rewrite-native / keep-thin / keep-python / locked / no-source."""
    if locked:
        return "locked", "already in locked/, no action"
    if language == "python":
        # source IS python - main.py is the correct implementation
        return "keep-python", "tool's upstream is itself Python"
    if native_sources:
        return "already-native", (
            f"native {language} source already present ({len(native_sources)} file"
            + ("s)" if len(native_sources) > 1 else ")")
        )
    if not main_py.get("present"):
        return "investigate", "no main.py present and no native source detected"
    if main_py.get("thin_wrapper") and bundled_binary:
        # main.py just exec's a bundled native binary - acceptable
        return "keep-thin", (
            f"main.py is thin exec wrapper around bundled {bundled_binary['kind']} binary "
            f"({bundled_binary['name']})"
        )
    if main_py.get("is_scaffold") and not bundled_binary:
        return (
            "scaffold-stub",
            "scaffold main.py with no bundled binary - low yield, needs native rewrite",
        )
    # main.py has substantive logic but should be native
    return "rewrite-native", (
        f"substantive Python ({main_py.get('lines_substantive')} lines, "
        f"{main_py.get('def_count')} funcs) implementing a {language} tool"
    )


def audit_one(
    slug_dir: Path, board_by_slug: dict[str, Any], lang_by_slug: dict[str, Any]
) -> dict[str, Any]:
    slug = slug_dir.name
    base = slug.split(".", 1)[0]
    board = board_by_slug.get(base) or {}
    lang_entry = lang_by_slug.get(base) or {}
    source_lang = _detect_source_language(slug, lang_entry)
    classification = lang_entry.get("classification") or "unknown"
    main_py = _classify_main_py(slug_dir / "main.py")
    native_sources = _find_native_source(slug_dir, source_lang)
    bundled_binary = _find_bundled_binary(slug_dir, slug)
    compile_sh = _read_compile_sh(slug_dir)
    score = float(board.get("best_score") or 0.0)
    passed = int(board.get("best_passed") or 0)
    runnable = int(board.get("best_runnable_total") or 0)
    locked = bool(board.get("locked_dir"))
    action, reason = _route_action(
        language=source_lang,
        main_py=main_py,
        native_sources=native_sources,
        bundled_binary=bundled_binary,
        classification=classification,
        score=score,
        locked=locked,
    )
    return {
        "slug": slug,
        "base_slug": base,
        "score": score,
        "passed": passed,
        "runnable": runnable,
        "source_language": source_lang,
        "classification": classification,
        "locked": locked,
        "main_py": main_py,
        "native_sources_present": [str(p.relative_to(slug_dir)) for p in native_sources],
        "bundled_binary": bundled_binary,
        "uses_bundled_in_compile": "/usr/local/bin/" in compile_sh
        or "cp ./" in compile_sh
        or "exec " in compile_sh
        and ("$bin" in compile_sh or bundled_binary is not None),
        "action": action,
        "reason": reason,
    }


def main() -> int:
    board = _load_json(BOARD_JSON) or []
    classifier = _load_json(CLASSIFIER_JSON) or []
    board_by_slug = {row["base_slug"]: row for row in board if "base_slug" in row}
    lang_by_slug = {row["base_slug"]: row for row in classifier if "base_slug" in row}
    valid_slugs = {row.get("slug") for row in board if row.get("slug")}

    rows: list[dict[str, Any]] = []
    for d in sorted(OVERRIDES_DIR.iterdir()):
        if not d.is_dir():
            continue
        if valid_slugs and d.name not in valid_slugs:
            continue
        rows.append(audit_one(d, board_by_slug, lang_by_slug))

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")

    # Summaries
    from collections import Counter, defaultdict

    by_action = Counter(r["action"] for r in rows)
    by_action_lang: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_action_lang[r["action"]][r["source_language"]] += 1

    rewrite_rows = [r for r in rows if r["action"] == "rewrite-native"]
    rewrite_rows.sort(key=lambda r: -r["score"])

    scaffold_rows = [r for r in rows if r["action"] == "scaffold-stub"]
    scaffold_rows.sort(key=lambda r: -r["score"])

    lines: list[str] = []
    lines.append("# ProgramBench language-routing audit\n\n")
    lines.append("> Generated by `scripts/pb_language_audit.py`. ")
    lines.append("Scans every `per_tool_overrides/<slug>/` to flag tools where ")
    lines.append("the current Python implementation belongs in a native language ")
    lines.append("(Go / Rust / C / C++) per the tool's upstream source.\n\n")

    lines.append("## Summary by action\n\n")
    lines.append("| action | count | meaning |\n|---|---:|---|\n")
    explanations = {
        "rewrite-native": "main.py has substantive Python logic but the upstream tool is in a native language. **Convert to native.**",
        "scaffold-stub": "Scaffold stub main.py + no bundled binary. Needs a native implementation.",
        "already-native": "Native source file(s) already present in the override. No conversion needed.",
        "keep-thin": "main.py is a thin exec-wrapper over a bundled native binary. Acceptable.",
        "keep-python": "Upstream is itself Python (eva, amber). main.py is the right home.",
        "locked": "Already archived in `corpus/programbench/locked/`. No action.",
        "investigate": "main.py missing. Needs manual triage.",
    }
    for action in (
        "rewrite-native",
        "scaffold-stub",
        "already-native",
        "keep-thin",
        "keep-python",
        "locked",
        "investigate",
    ):
        n = by_action.get(action, 0)
        if n == 0:
            continue
        lines.append(f"| **{action}** | {n} | {explanations.get(action, '')} |\n")
    lines.append("\n")

    lines.append("## rewrite-native breakdown by source language\n\n")
    if rewrite_rows:
        c = Counter(r["source_language"] for r in rewrite_rows)
        for lang, n in c.most_common():
            lines.append(f"- **{lang}**: {n}\n")
        lines.append("\n")
        lines.append("### rewrite-native tools (sorted by current score)\n\n")
        lines.append(
            "| score | passed/runnable | lang | class | py_lines | py_defs | bundled_binary | slug |\n"
        )
        lines.append("|---:|---:|---|---|---:|---:|---|---|\n")
        for r in rewrite_rows:
            bb = r["bundled_binary"]
            bb_str = f"{bb['name']} ({bb['kind']})" if bb else "—"
            lines.append(
                f"| {r['score']:.1f} | {r['passed']}/{r['runnable']} | {r['source_language']} | "
                f"{r['classification']} | {r['main_py'].get('lines_substantive', 0)} | "
                f"{r['main_py'].get('def_count', 0)} | {bb_str} | `{r['base_slug']}` |\n"
            )
        lines.append("\n")
    else:
        lines.append("_None._\n\n")

    lines.append("## scaffold-stub tools (low-yield Python stubs, need native)\n\n")
    if scaffold_rows:
        lines.append("| score | passed/runnable | lang | py_lines | bundled_binary | slug |\n")
        lines.append("|---:|---:|---|---:|---|---|\n")
        for r in scaffold_rows[:40]:
            bb = r["bundled_binary"]
            bb_str = f"{bb['name']} ({bb['kind']})" if bb else "—"
            lines.append(
                f"| {r['score']:.1f} | {r['passed']}/{r['runnable']} | {r['source_language']} | "
                f"{r['main_py'].get('lines_substantive', 0)} | {bb_str} | `{r['base_slug']}` |\n"
            )
        if len(scaffold_rows) > 40:
            lines.append(f"\n_({len(scaffold_rows) - 40} more scaffold stubs omitted)_\n")
        lines.append("\n")
    else:
        lines.append("_None._\n\n")

    lines.append("## keep-thin tools (acceptable: thin wrapper over bundled native binary)\n\n")
    thin_rows = [r for r in rows if r["action"] == "keep-thin"]
    thin_rows.sort(key=lambda r: -r["score"])
    if thin_rows:
        lines.append("| score | lang | bundled_binary | slug |\n|---:|---|---|---|\n")
        for r in thin_rows[:40]:
            bb = r["bundled_binary"]
            bb_str = f"{bb['name']} ({bb['kind']})" if bb else "—"
            lines.append(
                f"| {r['score']:.1f} | {r['source_language']} | {bb_str} | `{r['base_slug']}` |\n"
            )
        if len(thin_rows) > 40:
            lines.append(f"\n_({len(thin_rows) - 40} more thin wrappers omitted)_\n")
        lines.append("\n")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("".join(lines), encoding="utf-8")

    # Console summary
    print("ProgramBench language-routing audit")
    print("=" * 60)
    print(f"tools audited:  {len(rows)}")
    for action in (
        "rewrite-native",
        "scaffold-stub",
        "already-native",
        "keep-thin",
        "keep-python",
        "locked",
        "investigate",
    ):
        n = by_action.get(action, 0)
        if n:
            print(f"  {action:18s} {n}")
    print()
    print(f"rewrite-native ({len(rewrite_rows)}) by source language:")
    if rewrite_rows:
        c = Counter(r["source_language"] for r in rewrite_rows)
        for lang, n in c.most_common():
            print(f"  {lang:8s} {n}")
    print()
    print(f"wrote: {OUT_MD.relative_to(ROOT)}")
    print(f"wrote: {OUT_JSON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
