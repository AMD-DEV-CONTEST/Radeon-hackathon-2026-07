#!/usr/bin/env python3
"""pb_lock_agent.py — ProgramBench lock acceleration agent interface.

Designed for Claude, Codex, and Gemini to call directly. Reads the live corpus,
diagnoses failures from eval JSON tracebacks, and generates actionable context.
No external API calls. Python orchestration only — tools always build native.

Commands:
  diagnose <slug>    Cluster failures from latest eval JSON by type/rc/assertion.
  context  <slug>    Generate full AI-actionable markdown context package.
  fix-infra <slug>   Deterministically regen compile.sh from canonical template.
  fix-deps  <slug>   Scan source manifests for missing build deps → apt install line.
  pack      <slug>   Pack per_tool_overrides/<slug>/ and lint before deploy.
  lint      <slug>   Footgun check on current compile.sh (E1-E4, W1-W2).
  queue              Show top targets from NATIVE_REJECT_FIX_QUEUE.md with classes.

Native guard: every command rejects Python-wrapper submissions. compile.sh MUST
build from native source (Rust/Go/C/C++). Python is allowed only for test harness
orchestration (conftest.py, pytest.ini) — never for the compiled tool itself.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo-relative anchors
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
BOARD_JSON = REPO / "logs" / "programbench_lock_board.json"
EVAL_INDEX_JSON = REPO / "corpus" / "programbench" / "eval_index.json"
OVERRIDES = REPO / "corpus" / "programbench" / "per_tool_overrides"
LOCKED = REPO / "corpus" / "programbench" / "locked"
QUEUE_MD = REPO / "logs" / "programbench_factory" / "NATIVE_REJECT_FIX_QUEUE.md"
TEMPLATE_PY = REPO / "scripts" / "pb_compile_template.py"
LINT_PY = REPO / "scripts" / "pb_compile_lint.py"
PACK_PY = REPO / "scripts" / "pb_pack_candidate.py"

NATIVE_EXTENSIONS = {".rs", ".go", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"}
NATIVE_MANIFESTS = {"Cargo.toml", "go.mod", "CMakeLists.txt", "Makefile", "configure"}

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def detect_lang(source_dir: Path) -> str | None:
    """Detect native language from source directory contents."""
    if (source_dir / "Cargo.toml").exists():
        return "rust"
    if (source_dir / "go.mod").exists():
        return "go"
    exts = Counter(f.suffix for f in source_dir.rglob("*") if f.is_file())
    cpp_count = exts.get(".cpp", 0) + exts.get(".cc", 0) + exts.get(".cxx", 0)
    c_count = exts.get(".c", 0)
    if cpp_count > 0:
        return "cpp"
    if c_count > 0:
        return "c"
    if exts.get(".rs", 0) > 0:
        return "rust"
    return None


def native_guard(source_dir: Path, slug: str) -> str:
    """Return native language or abort if source is Python-only."""
    if not source_dir.exists():
        sys.exit(f"[ERROR] No source/ directory at {source_dir}. Run pb_pack_candidate.py first.")
    lang = detect_lang(source_dir)
    if lang is None:
        # Check for Python files only
        py_files = list(source_dir.rglob("*.py"))
        if py_files:
            sys.exit(
                f"[REJECT] {slug}: source contains only Python files — "
                "this is a Python wrapper, not a native build. "
                "Native guard violated. Use a real upstream source tree."
            )
        sys.exit(f"[ERROR] {slug}: cannot detect language in {source_dir}")
    return lang


# ---------------------------------------------------------------------------
# Board lookup
# ---------------------------------------------------------------------------


def load_board() -> list[dict]:
    if BOARD_JSON.exists():
        with BOARD_JSON.open(encoding="utf-8") as f:
            return json.load(f)
    if EVAL_INDEX_JSON.exists():
        with EVAL_INDEX_JSON.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            rows = data.get("tools") or data.get("entries") or data.get("results")
            if isinstance(rows, list):
                return rows
    sys.exit(f"[ERROR] No ProgramBench index found: {BOARD_JSON} or {EVAL_INDEX_JSON}")


def find_entry(board: list[dict], slug: str) -> dict | None:
    """Find board entry — accepts any of these forms:
    - board short slug:        "nsh", "trdsql", "chamber"
    - board base_slug:         "segmentio__chamber"
    - override dirname:        "segmentio__chamber.5f93f5f"
    - repo substring:          "chamber" matches "segmentio__chamber"
    """
    slug_base = slug.split(".")[0] if "." in slug else slug
    # Pass 1: exact matches
    for entry in board:
        if entry.get("slug") == slug:
            return entry
        if entry.get("slug") == slug_base:
            return entry
        if entry.get("base_slug") == slug:
            return entry
        if entry.get("base_slug") == slug_base:
            return entry
        bs: str = entry.get("base_slug") or ""
        if bs and slug.startswith(bs):
            return entry
    # Pass 2: repo-name substring (e.g., "chamber" in "segmentio__chamber")
    for entry in board:
        bs = entry.get("base_slug") or ""
        repo_part = bs.split("__")[-1] if "__" in bs else bs
        if repo_part == slug or repo_part == slug_base:
            return entry
    return None


def resolve_override_dir(slug: str) -> Path:
    """Return the per_tool_overrides directory for a slug.

    The overrides directory is always named owner__repo.hash. If the input
    is already that format (contains '__' and '.'), use it directly.
    Otherwise scan OVERRIDES for a dir whose name starts with slug.
    """
    if "__" in slug and "." in slug:
        # Already the full override dirname
        return OVERRIDES / slug
    # Scan for a match (slug may be base_slug like "nuta__nsh" or short "nsh")
    if OVERRIDES.exists():
        for d in sorted(OVERRIDES.iterdir()):
            if not d.is_dir():
                continue
            name = d.name
            # "nuta__nsh.bdd0702" starts with "nuta__nsh" or contains "nsh" after "__"
            if name.split(".")[0] == slug or name.startswith(slug + "."):
                return d
            # Short slug: match the repo part (after __)
            repo_part = name.split("__")[-1].split(".")[0] if "__" in name else name
            if repo_part == slug:
                return d
    return OVERRIDES / slug  # fallback, will error naturally


def get_eval_path(entry: dict, source_dir: Path | None = None) -> Path | None:
    """Return the best available eval JSON path for an entry."""
    candidates: list[Path] = []
    for key in ("best_eval_path", "latest_eval_path", "eval_path", "eval_report_path"):
        v = entry.get(key)
        if v:
            candidates.append(Path(v))
    if source_dir is not None:
        candidates.append(source_dir / "eval_report.json")
        candidates.extend(sorted(source_dir.glob("*.eval.json")))
    for p in candidates:
        if p.exists():
            return p
    return None


def entry_stat(entry: dict, *keys: str, default: int = 0) -> int:
    for key in keys:
        value = entry.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


# ---------------------------------------------------------------------------
# Eval JSON parsing + failure clustering
# ---------------------------------------------------------------------------

_RC_PATTERN = re.compile(r"(?:returncode|exit[_ ]code|rc)\s*[=!]=?\s*(\d+)", re.I)
_ASSERT_STDOUT = re.compile(r"assert\s+(?:r\.stdout|out|stdout)\s*==", re.I)
_ASSERT_STDERR = re.compile(r"assert\s+(?:r\.stderr|err|stderr)\s*==", re.I)
_ASSERT_IN = re.compile(r"assert\s+.*\s+in\s+(?:r\.stdout|out|stdout|r\.stderr|err)", re.I)
_ASSERT_RC = re.compile(r"assert\s+(?:rc|r\.returncode|returncode)\s*[=!]=", re.I)
_TIMEOUT = re.compile(r"TimeoutExpired|timeout", re.I)


def classify_failure(text: str) -> str:
    """Classify a single pytest failure traceback into a coarse type.

    Focuses on the line marked with '>' (the actual failing assertion),
    not earlier assertions in the same test that passed.
    """
    if _TIMEOUT.search(text):
        return "timeout"
    if "rc=127" in text or "returncode=127" in text or "exit code 127" in text.lower():
        return "rc127_binary_not_found"

    # Find the '>' marker line — that is the assertion which actually failed.
    failing_line = ""
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("> "):
            failing_line = stripped[2:]
            break

    target = failing_line if failing_line else text

    if _ASSERT_RC.search(target):
        m = _RC_PATTERN.search(target) or _RC_PATTERN.search(text)
        expected = m.group(1) if m else "?"
        return f"rc_mismatch(expected={expected})"
    if _ASSERT_STDOUT.search(target):
        return "stdout_exact_mismatch"
    if _ASSERT_STDERR.search(target):
        return "stderr_exact_mismatch"
    if _ASSERT_IN.search(target):
        return "stdout_partial_mismatch"
    return "other"


def cluster_failures(eval_path: Path) -> dict:
    """Return a structured failure report from an eval JSON."""
    with eval_path.open(encoding="utf-8", errors="replace") as f:
        data = json.load(f)

    results = data.get("test_results", [])
    failed = [r for r in results if r.get("status") == "failure"]
    not_run = [r for r in results if r.get("status") == "not_run"]
    passed = sum(1 for r in results if r.get("status") == "passed")

    clusters: dict[str, list[str]] = defaultdict(list)
    for r in failed:
        text = (r.get("extra") or {}).get("text", "")
        ftype = classify_failure(text)
        clusters[ftype].append(r.get("name", "?"))

    samples: dict[str, str] = {}
    for r in failed[:8]:
        text = (r.get("extra") or {}).get("text", "")
        ftype = classify_failure(text)
        if ftype not in samples:
            # Trim to first 400 chars of the interesting part
            snip = text[text.find("assert") if "assert" in text else 0 :][:400]
            samples[ftype] = snip

    return {
        "passed": passed,
        "failed": len(failed),
        "not_run": len(not_run),
        "runnable": passed + len(failed),
        "clusters": dict(clusters),
        "cluster_counts": {k: len(v) for k, v in clusters.items()},
        "samples": samples,
        "top_failing_tests": [r.get("name", "?") for r in failed[:10]],
    }


# ---------------------------------------------------------------------------
# Dependency scanning (build-deps class)
# ---------------------------------------------------------------------------

# Known pkg-config name → apt package mappings
_PKG_TO_APT: dict[str, str] = {
    "libgit2": "libgit2-dev",
    "openssl": "libssl-dev",
    "sqlite3": "libsqlite3-dev",
    "ncurses": "libncurses-dev",
    "boost": "libboost-all-dev",
    "libpng": "libpng-dev",
    "libjpeg": "libjpeg-dev",
    "zlib": "zlib1g-dev",
    "libcurl": "libcurl4-openssl-dev",
    "readline": "libreadline-dev",
    "freetype2": "libfreetype6-dev",
    "glib-2.0": "libglib2.0-dev",
    "gtk+-3.0": "libgtk-3-dev",
    "libxml-2.0": "libxml2-dev",
    "python3": "python3-dev",
    "lua": "liblua5.4-dev",
}

# Known Cargo crate → system lib mappings
_CRATE_TO_APT: dict[str, str] = {
    "openssl-sys": "libssl-dev pkg-config",
    "libgit2-sys": "libgit2-dev pkg-config",
    "libsqlite3-sys": "libsqlite3-dev",
    "libz-sys": "zlib1g-dev",
    "ncurses": "libncurses-dev",
    "alsa-sys": "libasound2-dev",
}


def resolve_deps(source_dir: Path, lang: str) -> list[str]:
    """Scan source manifests for system deps; return apt package list."""
    pkgs: set[str] = set()

    if lang == "rust":
        cargo = source_dir / "Cargo.toml"
        if cargo.exists():
            text = cargo.read_text(encoding="utf-8", errors="replace")
            for crate, apt in _CRATE_TO_APT.items():
                if crate in text:
                    pkgs.update(apt.split())
        # Also check build.rs
        for build_rs in source_dir.rglob("build.rs"):
            text = build_rs.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'probe_library\("([^"]+)"', text):
                pkg = m.group(1)
                if pkg in _PKG_TO_APT:
                    pkgs.add(_PKG_TO_APT[pkg])

    elif lang in ("c", "cpp"):
        cmake = source_dir / "CMakeLists.txt"
        if cmake.exists():
            text = cmake.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(
                r'(?:find_package|pkg_check_modules|pkg_search_module)\s*\(["\s]*([A-Za-z0-9_\-\.]+)',
                text,
                re.I,
            ):
                pkg = m.group(1).lower()
                if pkg in _PKG_TO_APT:
                    pkgs.add(_PKG_TO_APT[pkg])
        configure = source_dir / "configure.ac"
        if configure.exists():
            text = configure.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"AC_CHECK_LIB\s*\(\s*([^,\)]+)", text):
                lib = m.group(1).strip().strip('"')
                if lib in _PKG_TO_APT:
                    pkgs.add(_PKG_TO_APT[lib])

    elif lang == "go":
        # CGo deps appear in .go files as #cgo directives
        for go_file in list(source_dir.rglob("*.go"))[:50]:
            text = go_file.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"#cgo\s+pkg-config:\s*([^\n]+)", text):
                for pkg in m.group(1).split():
                    if pkg in _PKG_TO_APT:
                        pkgs.add(_PKG_TO_APT[pkg])

    return sorted(pkgs)


# ---------------------------------------------------------------------------
# Relevant locked lessons (by language, not keyword Jaccard)
# ---------------------------------------------------------------------------


def get_locked_by_lang(lang: str) -> list[tuple[str, str]]:
    """Return (tool_name, lessons_excerpt) for locked tools in the same language."""
    results = []
    if not LOCKED.exists():
        return results
    for tool_dir in sorted(LOCKED.iterdir()):
        if not tool_dir.is_dir():
            continue
        lf = tool_dir / "lessons.md"
        if not lf.exists():
            continue
        text = lf.read_text(encoding="utf-8", errors="replace")
        # Skip pure auto-drafts with no real content
        if "_No inline decision blocks_" in text and len(text) < 300:
            continue
        # Check if this tool is the right language
        # (lessons.md contains "Language: <lang>" or source has lang markers)
        if lang and f"Language: {lang}" not in text.lower() and lang not in text.lower():
            # Check source dir
            src = OVERRIDES / tool_dir.name
            if src.exists() and detect_lang(src) != lang:
                continue
        results.append((tool_dir.name, text[:800]))
    return results[:4]  # top 4 by language


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_diagnose(args: argparse.Namespace) -> None:
    slug: str = args.slug
    board = load_board()
    entry = find_entry(board, slug)
    if not entry:
        sys.exit(f"[ERROR] Slug not found in board: {slug}")

    source_dir = resolve_override_dir(slug)
    full_slug: str = source_dir.name
    lang = native_guard(source_dir, full_slug)

    eval_path = get_eval_path(entry, source_dir)
    if eval_path:
        report = cluster_failures(eval_path)
    else:
        passed = entry_stat(entry, "passed", "official_passed")
        total = entry_stat(entry, "runnable_total", "total", "official_total")
        failed = entry_stat(entry, "failed", "official_failed")
        not_run = entry_stat(entry, "not_run", "official_not_run")
        report = {
            "passed": passed,
            "failed": failed,
            "not_run": not_run,
            "runnable": total,
            "clusters": {},
            "cluster_counts": {},
            "samples": {},
            "top_failing_tests": [],
        }
    passed = report["passed"]
    runnable = report["runnable"]
    pct = passed / runnable * 100 if runnable else 0

    print(f"\n=== DIAGNOSE: {full_slug} ===")
    print(f"Language:  {lang}")
    print(f"Score:     {passed}/{runnable} = {pct:.1f}%")
    print(f"Failed:    {report['failed']}  Not-run: {report['not_run']}")
    print(
        f"Eval JSON: {eval_path if eval_path else 'not available (using eval_index aggregate only)'}"
    )
    print()
    print("Failure clusters:")
    for ftype, count in sorted(report["cluster_counts"].items(), key=lambda x: -x[1]):
        tests = report["clusters"][ftype][:3]
        print(f"  [{count:3d}] {ftype}")
        for t in tests:
            print(f"          {t}")
    print()
    if report["samples"]:
        print("Sample tracebacks (first per cluster):")
        for ftype, snip in list(report["samples"].items())[:3]:
            print(f"\n  --- {ftype} ---")
            for line in snip.splitlines()[:6]:
                print(f"  {line}")


def cmd_context(args: argparse.Namespace) -> None:
    slug = args.slug
    board = load_board()
    entry = find_entry(board, slug)
    if not entry:
        sys.exit(f"[ERROR] Slug not found in board: {slug}")

    source_dir = resolve_override_dir(slug)
    full_slug: str = source_dir.name
    lang = native_guard(source_dir, full_slug)

    eval_path = get_eval_path(entry, source_dir)
    report = cluster_failures(eval_path) if eval_path else {}

    passed = report.get("passed", entry_stat(entry, "passed", "official_passed"))
    runnable = report.get(
        "runnable",
        entry_stat(entry, "runnable_total", "total", "official_total"),
    )
    pct = passed / runnable * 100 if runnable else 0

    compile_sh = (
        (source_dir / "compile.sh").read_text(encoding="utf-8", errors="replace")
        if (source_dir / "compile.sh").exists()
        else "(not found)"
    )
    locked_lessons = get_locked_by_lang(lang)

    out = [
        f"# ProgramBench Lock Context: {full_slug}",
        "",
        f"**Language**: {lang}  **Score**: {passed}/{runnable} ({pct:.1f}%)  **Failures**: {report.get('failed', '?')}",
        "",
        f"**Eval JSON**: {eval_path if eval_path else 'not available (using eval_index aggregate only)'}",
        "",
        "## Failure Clusters",
        "",
    ]
    for ftype, count in sorted(report.get("cluster_counts", {}).items(), key=lambda x: -x[1]):
        out.append(f"- `{ftype}` — {count} tests")
    out.append("")

    out.append("## Failure Samples")
    out.append("")
    for ftype, snip in list(report.get("samples", {}).items())[:3]:
        out.append(f"### {ftype}")
        out.append("```")
        out.extend(snip.splitlines()[:8])
        out.append("```")
        out.append("")

    out.append("## Current compile.sh")
    out.append("")
    out.append("```sh")
    out.extend(compile_sh.splitlines()[:80])
    out.append("```")
    out.append("")

    if locked_lessons:
        out.append(f"## Locked Tools in Same Language ({lang})")
        out.append("")
        for name, excerpt in locked_lessons:
            out.append(f"### {name}")
            out.append("```")
            out.extend(excerpt.splitlines()[:20])
            out.append("```")
            out.append("")

    out.append("## Native Language Rule")
    out.append("")
    out.append(f"- Detected language: **{lang}**")
    out.append(
        "- compile.sh MUST build from native source (no Python wrappers for the tool binary)"
    )
    out.append(
        "- conftest.py / pytest.ini in compile.sh is OK — those are test harness, not the tool"
    )
    out.append("")
    out.append("## Next Action")
    out.append("")
    clusters = report.get("cluster_counts", {})
    if clusters.get("rc127_binary_not_found", 0) > 5:
        out.append("**Class: infra-path / build-deps** — binary not installed.")
        out.append("Run: `python scripts/pb_lock_agent.py fix-deps " + full_slug + "`")
        out.append("Then: `python scripts/pb_lock_agent.py fix-infra " + full_slug + "`")
    elif (
        sum(v for k, v in clusters.items() if "rc_mismatch" in k or "infra" in k)
        > report.get("failed", 1) * 0.7
    ):
        out.append("**Class: behavioral-regression** — exit codes differ from golden.")
        out.append("Cluster the rc values, find the test branch expecting each code, patch source.")
    else:
        out.append("**Class: behavioral** — stdout/stderr content mismatch.")
        out.append(
            "Read the full traceback for each failing test; find common output pattern diff."
        )

    print("\n".join(out))


def cmd_fix_infra(args: argparse.Namespace) -> None:
    slug = args.slug
    source_dir = resolve_override_dir(slug)
    full_slug: str = source_dir.name
    lang = native_guard(source_dir, full_slug)

    # Infer tool name from slug (owner__repo.hash → repo)
    tool_name = full_slug.split("__")[-1].split(".")[0] if "__" in full_slug else full_slug

    compile_out = source_dir / "compile.sh"
    backup = source_dir / "compile.sh.bak"
    if compile_out.exists():
        compile_out.rename(backup)
        print(f"[backup] {backup}")

    result = subprocess.run(
        [
            sys.executable,
            str(TEMPLATE_PY),
            "--lang",
            lang,
            "--tool",
            tool_name,
            "-o",
            str(compile_out),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[ERROR] Template generation failed:\n{result.stderr}")
        if backup.exists():
            backup.rename(compile_out)
        sys.exit(1)

    print(f"[OK] Generated {compile_out}")
    print(f"     Lang: {lang}  Tool: {tool_name}")
    print(f"     Restore with: mv {backup} {compile_out}")
    print()
    print("[lint]")
    subprocess.run([sys.executable, str(LINT_PY), str(compile_out), "--tool", tool_name])


def cmd_fix_deps(args: argparse.Namespace) -> None:
    slug = args.slug
    source_dir = resolve_override_dir(slug)
    full_slug: str = source_dir.name
    lang = native_guard(source_dir, full_slug)

    pkgs = resolve_deps(source_dir, lang)
    if not pkgs:
        print(
            f"[OK] No system deps detected for {full_slug} ({lang}). Build may be self-contained."
        )
        return

    apt_line = "apt-get update -qq && apt-get install -y -qq " + " ".join(pkgs)
    print(f"[DEPS] {full_slug} ({lang}) requires:")
    for p in pkgs:
        print(f"  {p}")
    print()
    print("Add this block to compile.sh BEFORE the build stage:")
    print()
    print("```sh")
    print("# Install system build deps")
    print(f"{apt_line} 2>/dev/null || true")
    print("```")
    print()
    print("Or run fix-infra to regen the full compile.sh and add Stage-0 manually.")


def cmd_pack(args: argparse.Namespace) -> None:
    slug = args.slug
    source_dir = resolve_override_dir(slug)
    full_slug: str = source_dir.name
    lang = native_guard(source_dir, full_slug)
    print(f"[native] {full_slug} -> language: {lang}")

    compile_sh = source_dir / "compile.sh"
    if compile_sh.exists():
        print("[lint]")
        r = subprocess.run(
            [sys.executable, str(LINT_PY), str(compile_sh)],
            capture_output=True,
            text=True,
        )
        print(r.stdout.strip())
        if "ERROR" in r.stdout:
            sys.exit("[ABORT] Lint errors — fix before deploying to Hetzner.")

    staging = (
        REPO / ".determinex_staging" / f"pb_{full_slug.replace('__', '_').replace('.', '_')}_agent"
    )
    result = subprocess.run(
        [sys.executable, str(PACK_PY), full_slug, "--run-root", str(staging)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr)
        sys.exit("[ERROR] Pack failed.")
    print(result.stdout.strip())
    print(f"\n[OK] Staged at: {staging}")
    print(f"     Next: python scripts/pb_export_hetzner_shard.py --run-root {full_slug}={staging}")


def cmd_lint(args: argparse.Namespace) -> None:
    slug = args.slug
    source_dir = resolve_override_dir(slug)
    compile_sh = source_dir / "compile.sh"
    if not compile_sh.exists():
        sys.exit(f"[ERROR] No compile.sh at {compile_sh}")
    subprocess.run([sys.executable, str(LINT_PY), str(compile_sh)])


def cmd_queue(_args: argparse.Namespace) -> None:
    if not QUEUE_MD.exists():
        sys.exit(f"[ERROR] Queue not found: {QUEUE_MD}")
    lines = QUEUE_MD.read_text(encoding="utf-8", errors="replace").splitlines()
    # Print header + first 30 data rows
    for line in lines[:35]:
        print(line)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    # Force UTF-8 output on Windows (avoids cp1252 encode errors for Unicode arrows etc.)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(
        description="ProgramBench lock acceleration agent. Use for diagnose/fix/pack cycles.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    for cmd in ("diagnose", "context", "fix-infra", "fix-deps", "pack", "lint"):
        p = sub.add_parser(cmd)
        p.add_argument("slug", help="full slug (owner__repo.hash) or base_slug")

    sub.add_parser("queue", help="Show top targets from fix queue")

    args = ap.parse_args()
    dispatch = {
        "diagnose": cmd_diagnose,
        "context": cmd_context,
        "fix-infra": cmd_fix_infra,
        "fix-deps": cmd_fix_deps,
        "pack": cmd_pack,
        "lint": cmd_lint,
        "queue": cmd_queue,
    }
    dispatch[args.cmd](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
