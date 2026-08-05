#!/usr/bin/env python3
"""
pb_language_audit.py — Determinex ProgramBench Language Core Audit
================================================================
Audits all 200 ProgramBench tools for:
  1. Detected implementation language
  2. Whether the language is in the "base language core" set
  3. Whether the tool has a submission available

Writes:
  - corpus/programbench/language_audit.json    — machine-readable
  - corpus/programbench/language_audit.md      — human-readable for Gemini/Claude

Tools WITHOUT a core language are placed at the BOTTOM of the eval queue.
This is what "decent shots at real climbing" means — core-language tools have
known build patterns (compile.sh templates) and predictable test behavior.

Core languages: Rust, Go, C, C++, Python, JavaScript, TypeScript
Non-core: Java, Haskell, Nix, Lua, Ruby, Scala, Kotlin, unknown
"""

import datetime
import json
import pathlib

ROOT = pathlib.Path(__file__).parent.parent.parent.resolve()
INDEX_PATH = ROOT / "corpus" / "programbench" / "eval_index.json"
LOCKED_DIR = ROOT / "corpus" / "programbench" / "locked"
OUT_JSON = ROOT / "corpus" / "programbench" / "language_audit.json"
OUT_MD = ROOT / "corpus" / "programbench" / "language_audit.md"

CORE_LANGUAGES = {"rust", "go", "c", "cpp", "python", "javascript", "typescript"}
NON_CORE_LANGUAGES = {"java", "haskell", "nix", "lua", "ruby", "perl", "scala", "kotlin"}

# Hand-curated language map from source inspection + ProgramBench task metadata
LANGUAGE_MAP = {
    "angle-grinder": "rust",
    "argc": "rust",
    "ascii-image-converter": "rust",
    "bore": "rust",
    "boyter__scc.515f91c": "go",
    "chroma": "rust",
    "clog-cli": "rust",
    "code-minimap": "rust",
    "cmatrix": "c",
    "csview": "rust",
    "curlie": "rust",
    "deadnix": "rust",  # nix tool but written in rust
    "diffr": "rust",
    "dsq": "go",
    "dupl": "go",
    "elfcat": "rust",
    "entr": "c",
    "eureka": "rust",
    "eva": "rust",
    "fasttext": "cpp",
    "fblog": "rust",
    "flamelens": "rust",
    "fzf": "go",
    "genact": "rust",
    "git-trim": "go",
    "go-mod-outdated": "go",
    "gping": "rust",
    "grex": "rust",
    "gron": "go",
    "hck": "rust",
    "hex": "rust",
    "htmlq": "rust",
    "hyperfine": "rust",
    "i3-style": "python",
    "igrep": "rust",
    "jplot": "go",
    "json-tui": "rust",
    "jq": "c",
    "keifu": "rust",
    "loop": "rust",
    "miniserve": "rust",
    "muffet": "go",
    "monolith": "rust",
    "ngrrram": "rust",
    "nomino": "rust",
    "nsh": "rust",
    "oha": "rust",
    "ov": "rust",
    "parqeye": "python",
    "pastel": "rust",
    "pier": "rust",
    "pingu": "rust",
    "quickjs": "c",
    "rhit": "rust",
    "richgo": "go",
    "ripgrep": "rust",
    "ripsecrets": "rust",
    "rnr": "rust",
    "rumdl": "rust",
    "run": "rust",
    "rustowl": "rust",
    "sd": "rust",
    "seqtk": "c",
    "shellharden": "rust",
    "stathissideris__ditaa": "java",
    "tailspin": "rust",
    "tex-fmt": "rust",
    "thokr": "rust",
    "tparse": "go",
    "trdsql": "go",
    "tuc": "rust",
    "xq": "rust",
    "xsv": "rust",
    "xz": "c",
    "yj": "go",
    "yq": "go",
    "zip-password-finder": "rust",
    "zoxide": "rust",
    # Board-cache tools
    "sayanarijit__xplr": "rust",
    "rust-embedded__svd2rust": "rust",
    "tarka__xcp": "rust",
    "antonmedv__walk": "go",
    "nikoladucak__caps-log": "cpp",
    "nachoparker__dutree": "rust",
    "tinycc__tinycc": "c",
    "ggreer__the_silver_searcher": "c",
    "isona__dirble": "rust",
    "skeema__skeema": "go",
    "gabotechs__dep-tree": "go",
    "nikolassv__bartib": "rust",
    "astaxie__bat": "go",
    "ninja-build__ninja": "cpp",
    "ksxgithub__parallel-disk-usage": "rust",
    "chmln__handlr": "rust",
    "lfos__calcurse": "c",
    "madler__pigz": "c",
    "blacknon__hwatch": "rust",
    "ariga__atlas": "go",
    "bootandy__dust": "rust",
    "kisielk__errcheck": "go",
    "segmentio__chamber": "go",
    "tree-sitter__tree-sitter": "c",
    "codesnap-rs__codesnap": "rust",
    "canop__broot": "rust",
    "tomarrell__wrapcheck": "go",
    "mkj__dropbear": "c",
    "jarun__nnn": "c",
    "jesseduffield__lazygit": "go",
    "oppiliappan__statix": "rust",
    "guumaster__hostctl": "go",
    "ammarabouzor__tui-journal": "rust",
    "byron__dua-cli": "rust",
    "crowdagger__crowbook": "rust",
    "hpjansson__chafa": "c",
    "zevv__duc": "c",
    "cmatsuoka__figlet": "c",
    "git-bahn__git-graph": "rust",
    "stacked-git__stgit": "python",
    "dalance__amber": "rust",
    "mfridman__tparse": "go",
    "sheepla__pingu": "rust",
    "kyoh86__richgo": "go",
    "hatoo__oha": "rust",
    "hatao__oha": "rust",
}


def detect_from_source(slug: str) -> str:
    """Fallback: detect from source files in locked/ dir."""
    locked = LOCKED_DIR / slug / "source"
    if not locked.exists():
        # Try alternate slug forms
        for d in LOCKED_DIR.iterdir():
            if d.is_dir() and slug.lower() in d.name.lower():
                locked = d / "source"
                break
    if locked.exists():
        exts = [f.suffix for f in locked.rglob("*") if f.is_file()]
        if ".rs" in exts:
            return "rust"
        if ".go" in exts:
            return "go"
        if ".cpp" in exts or ".cc" in exts:
            return "cpp"
        if ".c" in exts:
            return "c"
        if ".py" in exts:
            return "python"
        if ".java" in exts:
            return "java"
        if ".hs" in exts:
            return "haskell"
        if ".js" in exts:
            return "javascript"
        if ".ts" in exts:
            return "typescript"
    return "unknown"


def main():
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

    audit_rows = []
    for entry in data:
        slug = entry["slug"]
        status = entry["status"]
        score = entry.get("official_score_pct", 0)
        passed = entry.get("official_passed", 0)
        total = entry.get("official_total", 0)
        not_run = entry.get("official_not_run", 0)

        # Determine language
        lang = LANGUAGE_MAP.get(slug, "")
        if not lang:
            lang = detect_from_source(slug)

        is_core = lang in CORE_LANGUAGES
        is_non_core = lang in NON_CORE_LANGUAGES or lang == "unknown"

        # Check submission availability
        ep = entry.get("eval_report_path", "")
        has_submission = False
        if ep:
            p = pathlib.Path(ep).parent
            has_submission = (p / "submission.tar.gz").exists()

        # Ceiling-confirmed don't need evals
        skip = status == "ceiling_confirmed"

        audit_rows.append(
            {
                "slug": slug,
                "status": status,
                "lang": lang,
                "is_core": is_core,
                "has_submission": has_submission,
                "skip": skip,
                "score_pct": score,
                "passed": passed,
                "total": total,
                "not_run": not_run,
            }
        )

    # Sort for queue: ceiling out, then core first, then by score desc
    runnable = [r for r in audit_rows if not r["skip"]]
    core_tools = sorted([r for r in runnable if r["is_core"]], key=lambda x: -x["score_pct"])
    non_core_tools = sorted(
        [r for r in runnable if not r["is_core"]], key=lambda x: -x["score_pct"]
    )
    ceiling = [r for r in audit_rows if r["skip"]]

    ordered = core_tools + non_core_tools + ceiling

    # Write JSON
    OUT_JSON.write_text(json.dumps(ordered, indent=2), encoding="utf-8")

    # Write Markdown
    lines = [
        "# ProgramBench Language Core Audit",
        "",
        f"> Generated: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        ">",
        "> **Core languages** (Rust, Go, C, C++, Python, JS, TS) have established compile.sh patterns",
        "> and predictable test behavior. These run FIRST.",
        ">",
        "> **Non-core languages** (Java, Haskell, unknown, etc.) need extra infra work.",
        "> These run LAST.",
        "",
        "## Summary",
        "",
        "| Category | Count |",
        "|----------|-------|",
        f"| Core language tools | {len(core_tools)} |",
        f"| Non-core language tools | {len(non_core_tools)} |",
        f"| Ceiling-confirmed (skip) | {len(ceiling)} |",
        f"| **Total** | **{len(audit_rows)}** |",
        "",
        "## Language Breakdown",
        "",
    ]

    lang_counts = {}
    for r in runnable:
        lang_counts[r["lang"]] = lang_counts.get(r["lang"], 0) + 1
    for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
        core_flag = "✓ core" if lang in CORE_LANGUAGES else "✗ non-core"
        lines.append(f"- **{lang}** ({core_flag}): {count} tools")

    lines += [
        "",
        "## Core Language Queue (run first)",
        "",
        "| # | Slug | Lang | Score | Status | Has Sub |",
        "|---|------|------|-------|--------|---------|",
    ]
    for i, r in enumerate(core_tools):
        sub = "✓" if r["has_submission"] else "✗"
        lines.append(
            f"| {i + 1} | {r['slug']} | {r['lang']} | {r['score_pct']:.1f}% "
            f"({r['passed']}/{r['total']}) | {r['status']} | {sub} |"
        )

    lines += [
        "",
        "## Non-Core Language Queue (run last — needs infra work first)",
        "",
        "> [!WARNING]",
        "> These tools require extra compile.sh patterns or language runtimes.",
        "> Gemini Flash: do NOT attempt to lock these without first adding the runtime.",
        "",
        "| # | Slug | Lang | Score | Status | Has Sub |",
        "|---|------|------|-------|--------|---------|",
    ]
    for i, r in enumerate(non_core_tools):
        sub = "✓" if r["has_submission"] else "✗"
        lines.append(
            f"| {i + 1} | {r['slug']} | {r['lang']} | {r['score_pct']:.1f}% "
            f"({r['passed']}/{r['total']}) | {r['status']} | {sub} |"
        )

    lines += [
        "",
        "## Ceiling-Confirmed (skip entirely)",
        "",
    ]
    for r in ceiling:
        lines.append(f"- {r['slug']} ({r['lang']}): irreconcilable ceiling, do not attempt")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print("Language audit written:")
    print(f"  JSON: {OUT_JSON}")
    print(f"  MD:   {OUT_MD}")
    print(f"\nCore language tools: {len(core_tools)}")
    print(f"Non-core tools:      {len(non_core_tools)}")
    print(f"Ceiling (skip):      {len(ceiling)}")
    print("\nNon-core tools that need infra work:")
    for r in non_core_tools:
        print(f"  {r['slug']}: {r['lang']} ({r['score_pct']:.1f}%)")


if __name__ == "__main__":
    main()
