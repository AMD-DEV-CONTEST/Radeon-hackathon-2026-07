#!/usr/bin/env python3
"""
determinex_ingest.py -- The Universal Task Ingester (Adjudicator component A)
==========================================================================
"...take any bench and first run, take it in, understand it, realize it will
need these edits to work or to create this according to what is being asked."

This is the comprehension front of the loop. Pointed at an arbitrary repo or
benchmark task it has never seen, it derives -- deterministically, no LLM -- the
four things the rest of the pipeline needs:

    language     : which language(s) the task is in (extension census)
    build_system : how to build it (cargo / go / cmake / make / npm / gradle / pip)
    harness      : how it is verified (pytest / jest / junit / cargo test / go test)
    oracle       : the ground-truth surface (from determinex_oracle registry); if the
                   task ships NO tests, flag for synthesize_oracle()
    spec         : an inferred behavioral specification -- the asserted behaviors,
                   CLI surface, and invariants reverse-engineered from the tests,
                   so planning is PROACTIVE ("it will need these edits") rather than
                   purely try-fail-inject.

The spec inference is intentionally evidence-based: it extracts the concrete
assertions, invoked argv, and test docstrings already present, rather than
guessing intent. That keeps it honest -- it reports what the tests demand, which
is exactly the ground truth the solve loop must satisfy.

    from determinex_ingest import ingest
    u = ingest(Path("some_repo/"))
    print(u.language, u.harness, u.oracle, len(u.spec.behaviors))

CLI
---
    python scripts/determinex_ingest.py <repo_or_task_dir> [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
try:
    from determinex_oracle import _ORACLES  # registry: language -> Oracle
except Exception:
    _ORACLES = {}
try:
    from determinex_hw_profiler import detect_dialect_sources
    from determinex_hw_profiler import profile_repo as hw_profile_repo
except Exception:
    detect_dialect_sources = None
    hw_profile_repo = None


_LANG_BY_EXT = {
    ".rs": "rust",
    ".go": "go",
    ".py": "python",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".kt": "kotlin",
    ".java": "java",
    ".swift": "swift",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".cob": "cobol",
    ".cbl": "cobol",
    ".bas": "basic",
}

_BUILD_MARKERS = {
    "Cargo.toml": "cargo",
    "go.mod": "go",
    "CMakeLists.txt": "cmake",
    "Makefile": "make",
    "configure": "autotools",
    "package.json": "npm",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "pom.xml": "maven",
    "setup.py": "pip",
    "pyproject.toml": "pip",
    "Package.swift": "swiftpm",
}

_HARNESS_SIGNATURES = [
    ("pytest", re.compile(r"\bimport pytest\b|def test_|@pytest\.")),
    ("jest", re.compile(r"\b(describe|it|test)\s*\(|expect\(.*\)\.to")),
    ("cargo-test", re.compile(r"#\[test\]|#\[cfg\(test\)\]")),
    ("go-test", re.compile(r"func Test\w+\(t \*testing\.T\)")),
    ("junit", re.compile(r"@Test\b|org\.junit")),
]


@dataclass
class Spec:
    summary: str = ""
    cli_surface: list[str] = field(default_factory=list)  # observed argv/flags
    behaviors: list[str] = field(default_factory=list)  # asserted behaviors
    invariants: list[str] = field(default_factory=list)  # derived properties
    terms: dict = field(default_factory=dict)  # canonical verbiage
    # (extracted, never guessed)


@dataclass
class TaskUnderstanding:
    root: str
    language: str
    language_census: dict[str, int]
    build_system: str
    harness: str
    has_tests: bool
    oracle: str  # registered language oracle name, or "SYNTHESIZE"
    oracle_available: bool
    spec: Spec
    notes: list[str] = field(default_factory=list)
    hardware_profile: dict | None = None  # Pre-Flight Static Graph Profiler result, if a
    # known hardware-kernel dialect was auto-detected


_EXCLUDED_DIR_NAMES = (
    # VCS
    ".git",
    ".svn",
    ".hg",
    # Language dependency/package dirs
    "node_modules",
    "vendor",
    "target",
    "venv",
    ".venv",
    "env",
    ".env",
    # Interpreter/tool caches -- never source, and on a large repo can
    # dwarf real source by orders of magnitude (found live 2026-07-22: this
    # project's own .venv/scratch/corpus/.pytest_tmp_* dirs pushed a single
    # ingest() call past several minutes and multiple GB of resident memory
    # with the crash fixed but no exclusions beyond the original 4-item
    # list -- a general-purpose "point this at any repo" ingester needs to
    # skip these by default, not just avoid crashing on them).
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".uv-cache",
    ".cache",
    # Build/dist output
    "dist",
    "build",
    ".next",
    "out",
    # Editor/IDE
    ".vscode",
    ".idea",
    # "testdata" -- a well-established convention across many tools (Go's
    # own build explicitly ignores any "testdata/" dir for exactly this
    # reason: it's data a project studies/tests against, not the project's
    # own logic).
    "testdata",
    # This project's own ProgramBench reference corpus: ~150 archived OTHER
    # projects' real source (ffmpeg, sqlite, dropbear, tinycc, ...),
    # intentionally tracked in git (not gitignored, so the git-ls-files
    # path doesn't skip it) as reference material, not Determinex's own logic.
    # Found live 2026-07-22: 124,315 files here (89% of them .c) skewed
    # language census to "c" over this project's own actual python/
    # typescript, and in turn made oracle-verification look for a "c"
    # oracle that was never the right question for what a real chat-room
    # edit touches. NOT excluded by the more general name "corpus" --
    # scripts/corpus/ (a sibling, unrelated directory) holds REAL Determinex
    # Python source (corpus-management tooling), so a bare "corpus"
    # exclusion would have wrongly swallowed that too. "per_tool_overrides"
    # is the one uniquely-named directory that is *only* ever this vendored
    # archive (verified: appears nowhere else in the tracked tree).
    "per_tool_overrides",
    # Same story, second location: corpus/programbench/locked/<tool>/ and
    # corpus/swebench/locked/<tool>/ -- the OFFICIAL archived reference
    # source for each PB/SWE-bench "locked" tool (~12,000 files), same
    # vendored-not-Determinex's-own-code reasoning as per_tool_overrides
    # above. "locked" verified unique to these two paths in the tracked
    # tree (not a name used anywhere else in this repo).
    "locked",
    # corpus/programbench/pending_unlock/<tool>/source/ -- more of the same
    # vendored PB reference archive, one stage earlier in the pipeline
    # (not yet officially locked). Verified unique to this one path.
    "pending_unlock",
    # assurance/demo_workspaces/... and the rest of assurance/ generally:
    # this project's own proof-of-capability EVIDENCE store (demo runs,
    # screenshots, synthetic before/after fixtures for the Repo
    # Clinic/Maintenance Bay demos) -- verified every file under it is
    # demo/fixture/snapshot content, never Determinex's actual product
    # source, even where a stray .py/.js file looks real at a glance
    # (named demo_fixture/broken_fixture/historical_snapshot). Found live
    # 2026-07-22: discover_subprojects (below) was treating these
    # synthetic per-language demo projects as real subprojects needing
    # oracle verification.
    "assurance",
    # tests/fixtures/intake/{go,python,rust,ts}_broken -- INTENTIONALLY
    # broken fixtures for testing determinex_ingest's own build-adapter
    # detection (test_build_adapter_registry_lock.py). Verifying these
    # "must pass" would be verifying the exact opposite of their purpose.
    "go_broken",
    "python_broken",
    "rust_broken",
    "ts_broken",
)


_GIT_LS_FILES_TIMEOUT = 30


def _git_tracked_files(root: Path) -> list[Path] | None:
    """Ask git for the real file list (tracked + untracked-but-not-ignored)
    instead of walking the filesystem by hand. Automatically respects
    .gitignore/.git/info/exclude/global excludes -- far more correct AND
    far faster than hand-maintaining a directory-name exclusion list, since
    it reuses whatever the project itself already declared isn't real
    source. Found live 2026-07-22: this repo's own .venv/scratch/archive/
    release_build_work/.pytest_tmp_*/etc (all already gitignored) pushed a
    single ingest() call past several minutes and multiple GB of resident
    memory even with a hand-maintained exclusion list covering the common
    universal cases -- there is no bounded way to hand-enumerate every
    project's own huge-but-irrelevant directory names, but every git repo
    already has the authoritative answer sitting in .gitignore.
    Returns None (falls back to _walk_files_manual) if this isn't a git
    repo, git isn't on PATH, or the call fails for any reason -- ingest()
    must still work on a non-git task directory.
    """
    if not (root / ".git").exists():
        return None
    try:
        # encoding="utf-8", errors="replace" (NOT the default text=True,
        # which decodes with the Windows console codepage/cp1252) -- found
        # live 2026-07-22: this repo's own git ls-files output contains a
        # byte sequence cp1252 can't decode at all, crashing with
        # `UnicodeDecodeError: 'charmap' codec can't decode byte 0x81`
        # before a single file was even processed. Git paths are
        # byte-oriented, not intrinsically any encoding -- replace, don't
        # crash, on whatever doesn't decode as UTF-8.
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=str(root),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_LS_FILES_TIMEOUT,
        )
        if result.returncode != 0:
            return None
        return [root / rel for rel in result.stdout.split("\0") if rel]
    except Exception:
        return None


def _walk_files_manual(root: Path):
    """Hand-walked fallback for non-git workspaces. Two real bugs found live
    2026-07-22 (the FIRST time a chat-room turn ever reached oracle
    verification, after fixing the PATHEXT spawn bug -- every prior turn
    had errored out before ever exercising this code): (1) `p.is_file()`
    was called on every path BEFORE the node_modules/.git/etc exclusion
    check ran (`p.is_file() and not any(...)` evaluates the stat call
    first), so an unusual filesystem entry inside an excluded dir (here: a
    broken/reparse-point npm .bin shim,
    frontend/node_modules/.bin/.acorn-DALZbuMa) still got stat'd and raised
    `OSError: [WinError 1920] The file cannot be accessed by the system`,
    crashing the whole oracle check with nothing to do with the actual code
    being verified. (2) `_detect_build` didn't exclude those directories at
    all. Fix: skip excluded dirs by NAME before ever touching the
    filesystem, and treat any stat failure as "not a file" (skip) rather
    than propagating -- a broken symlink/junction/permission-denied entry
    should never be able to abort a whole repo scan.
    """
    for p in root.rglob("*"):
        if any(seg in _EXCLUDED_DIR_NAMES for seg in p.parts):
            continue
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        yield p


def _walk_files(root: Path):
    """Shared, crash-safe file walk for all three ingest scanners below.
    Prefers git's own tracked+untracked-but-not-ignored file list (see
    _git_tracked_files); falls back to a manual, exclusion-filtered,
    stat-failure-safe walk for non-git workspaces.

    No per-path is_file() re-check on the git branch -- `git ls-files` only
    ever lists blob paths, never directories, so it's already exactly the
    file list. Found live 2026-07-22: re-stat'ing every one of this repo's
    100,000+ tracked files individually (a real Windows syscall each) was
    itself a major slice of a still-too-slow ingest() call even after
    fixing the crash and the redundant-walk-per-marker bug. A tracked path
    that's gone missing from the working tree (rare: index/worktree
    mismatch) just surfaces as a normal FileNotFoundError wherever its
    content is later read (_infer_spec, _detect_harness's sample loop --
    both already wrap reads in try/except), not a crash here.

    _EXCLUDED_DIR_NAMES is still applied on the git branch, NOT just the
    manual fallback -- found live 2026-07-22 as a regression from the
    is_file()-removal optimization above: `git ls-files` only respects
    .gitignore, which does NOT cover intentionally-TRACKED-but-not-real-
    source directories (this project's own corpus/programbench/
    per_tool_overrides/, 124k+ files of vendored reference archives). An
    earlier version of this function dropped the per-path exclusion loop
    entirely when it stopped needing the per-path is_file() call, silently
    un-fixing every _EXCLUDED_DIR_NAMES entry added after the git-ls-files
    path was introduced, for any git workspace (i.e. every real repo).
    """
    git_files = _git_tracked_files(root)
    if git_files is not None:
        for p in git_files:
            if any(seg in _EXCLUDED_DIR_NAMES for seg in p.parts):
                continue
            yield p
        return
    yield from _walk_files_manual(root)


def _census_languages(files: list[Path]) -> dict[str, int]:
    c: Counter = Counter()
    for p in files:
        lang = _LANG_BY_EXT.get(p.suffix.lower())
        if lang:
            c[lang] += 1
    return dict(c.most_common())


def _detect_build(root: Path, files: list[Path]) -> str:
    # Fast path: the marker sitting directly at the workspace root, no walk
    # needed at all -- this resolves the overwhelming majority of real repos.
    for marker, system in _BUILD_MARKERS.items():
        if (root / marker).exists():
            return system
    # Nested marker (e.g. a subproject's go.mod) -- one pass over the
    # ALREADY-COMPUTED shared file list, not a separate walk per marker.
    # Found live 2026-07-22: the previous version called `_walk_files(root)`
    # (a full git-ls-files + is_file pass) once per marker -- 11 separate
    # full walks just for build detection, on top of census/harness each
    # doing their own -- ~13x redundant work on every single ingest() call.
    names = {p.name for p in files}
    for marker, system in _BUILD_MARKERS.items():
        if marker in names:
            return system
    return "unknown"


# build_system -> language, for the (common) case where a build marker
# unambiguously implies one oracle language. "npm" and the C-family build
# systems are deliberately absent -- they cover more than one real
# language (npm: JS or TS; make/cmake/autotools: C or C++), so those get
# resolved per-subproject by counting which extension actually dominates
# under that subproject's own directory (see _resolve_subproject_language).
_BUILD_MARKER_LANGUAGE: dict[str, str] = {
    "cargo": "rust",
    "go": "go",
    "gradle": "jvm",
    "maven": "jvm",
    "pip": "python",
    "swiftpm": "swift",
}
_C_FAMILY_BUILD_SYSTEMS = ("cmake", "make", "autotools")


@dataclass
class Subproject:
    path: Path
    language: str
    build_system: str


def _is_under(p: Path, base: Path) -> bool:
    try:
        p.relative_to(base)
        return True
    except ValueError:
        return False


def _resolve_subproject_language(system: str, proj_dir: Path, files: list[Path]) -> str | None:
    if system in _BUILD_MARKER_LANGUAGE:
        return _BUILD_MARKER_LANGUAGE[system]
    if system == "npm":
        ts = sum(1 for p in files if p.suffix.lower() in (".ts", ".tsx") and _is_under(p, proj_dir))
        js = sum(1 for p in files if p.suffix.lower() in (".js", ".jsx") and _is_under(p, proj_dir))
        if ts == 0 and js == 0:
            return None
        return "typescript" if ts >= js else "javascript"
    if system in _C_FAMILY_BUILD_SYSTEMS:
        cpp = sum(
            1
            for p in files
            if p.suffix.lower() in (".cpp", ".cc", ".cxx", ".hpp") and _is_under(p, proj_dir)
        )
        c = sum(1 for p in files if p.suffix.lower() == ".c" and _is_under(p, proj_dir))
        if cpp == 0 and c == 0:
            return None
        return "cpp" if cpp >= c else "c"
    return None


def discover_subprojects(root: Path) -> list[Subproject]:
    """Find EVERY real build-marker root in the workspace, not just
    whichever single language has the most files repo-wide (the old
    ingest().language model). A genuinely polyglot project -- this one:
    Python engine + Rust/Tauri frontend + Go/C/TS oracle targets -- has
    MULTIPLE real, independently buildable subprojects, each needing its
    own oracle run at its OWN path. Found live 2026-07-22: the old model
    picked "rust" (or whatever census's top language was) and ran `cargo
    check` at the WORKSPACE ROOT, which has no Cargo.toml at all -- the
    real one lives at frontend/src-tauri/. Ryan: "it should be fixed to
    where it all compiles and reports one way or the other" -- every real
    subproject, verified where it actually lives, not one guess for the
    whole tree."""
    files = list(_walk_files(root))
    by_marker: dict[str, list[Path]] = {}
    for p in files:
        if p.name in _BUILD_MARKERS:
            by_marker.setdefault(p.name, []).append(p.parent)

    subprojects: list[Subproject] = []
    seen_dirs: set[Path] = set()
    for marker, system in _BUILD_MARKERS.items():
        for proj_dir in sorted(set(by_marker.get(marker, ()))):
            if proj_dir in seen_dirs:
                continue
            language = _resolve_subproject_language(system, proj_dir, files)
            if language is None:
                continue
            seen_dirs.add(proj_dir)
            subprojects.append(Subproject(path=proj_dir, language=language, build_system=system))
    return _merge_tauri_pairs(subprojects)


def _merge_tauri_pairs(subprojects: list[Subproject]) -> list[Subproject]:
    """A Tauri app is discovered as TWO independent subprojects -- a rust
    one at <app>/src-tauri (Cargo.toml) and a typescript/javascript one at
    <app> itself (package.json) -- that are really one verifiable unit: a
    passing `cargo check` next to a broken frontend build (or vice versa)
    is not a real pass for the app. Collapse each such pair into a single
    "tauri" subproject rooted at <app>, verified by the composite
    determinex_oracle._verify_tauri (both halves), instead of reporting
    two separately-half-verified results for what is really one app."""
    tauri_backends = {
        sp.path.parent: sp
        for sp in subprojects
        if sp.language == "rust"
        and sp.path.name == "src-tauri"
        and (sp.path / "tauri.conf.json").exists()
    }
    if not tauri_backends:
        return subprojects
    consumed: set[Path] = set()
    merged: list[Subproject] = []
    for sp in subprojects:
        backend = tauri_backends.get(sp.path)
        if backend is not None and sp.language in ("typescript", "javascript"):
            merged.append(Subproject(path=sp.path, language="tauri", build_system="tauri"))
            consumed.add(sp.path)
            consumed.add(backend.path)
    for sp in subprojects:
        if sp.path not in consumed:
            merged.append(sp)
    return merged


def _detect_harness(files: list[Path]) -> tuple[str, bool, list[Path]]:
    test_files: list[Path] = []
    for p in files:
        n = p.name.lower()
        in_test_path = any(
            "test" in part.lower() or "spec" in part.lower() for part in p.parts[:-1]
        )
        looks_like_test = (
            n.startswith("test_")
            or n.endswith("_test.py")
            or n.endswith(".test.ts")
            or n.endswith(".test.js")
            or n.endswith("_test.go")
            or n.endswith("_test.rs")
            or n in ("tests.rs",)
            or "test" in n
            or "spec" in n
        )
        if (looks_like_test or in_test_path) and p.suffix.lower() in _LANG_BY_EXT:
            test_files.append(p)
    sample = ""
    for p in test_files[:25]:
        try:
            sample += p.read_text(encoding="utf-8", errors="replace")[:4000]
        except Exception:
            pass
    for name, pat in _HARNESS_SIGNATURES:
        if pat.search(sample):
            return name, bool(test_files), test_files
    return ("none", bool(test_files), test_files)


def _infer_spec(test_files: list[Path], language: str) -> Spec:
    behaviors: list[str] = []
    cli: set[str] = set()
    invariants: set[str] = set()
    for p in test_files[:80]:
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        # observed argv / flags from run("--flag", ...) and subprocess calls
        for m in re.finditer(r"""run\(\s*["']([^"']+)["']""", src):
            cli.add(m.group(1))
        for m in re.finditer(r"""["'](--?[a-zA-Z][\w-]*)["']""", src):
            cli.add(m.group(1))
        # asserted behaviors: test docstrings + assertion lines
        for m in re.finditer(
            r'def (test_\w+)\([^)]*\):\s*(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')?', src, re.DOTALL
        ):
            name = m.group(1)
            doc = (m.group(2) or m.group(3) or "").strip().splitlines()
            desc = doc[0].strip() if doc else name.replace("test_", "").replace("_", " ")
            behaviors.append(f"{name}: {desc}")
        # invariants from common property patterns
        if re.search(r"round.?trip|encode.*decode|decode.*encode", src, re.I):
            invariants.add("round-trip: encode then decode == identity")
        if re.search(r"idempoten", src, re.I):
            invariants.add("idempotence: f(f(x)) == f(x)")
        if re.search(r"returncode\s*==\s*0", src):
            invariants.add("valid invocations exit 0")
    # Canonical verbiage: mine the proper terms straight from test sources so
    # the reimpl never guesses flag long-names, metavars, possible-values, or
    # error templates. Shared engine with the eval-JSON term extractor.
    terms: dict = {}
    try:
        from determinex_term_extractor import mine_texts

        blobs = []
        for p in test_files[:80]:
            try:
                blobs.append(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                pass
        terms = mine_texts(blobs)
    except Exception:
        terms = {}

    summary = (
        f"{language} tool; {len(behaviors)} asserted behaviors across "
        f"{len(test_files)} test files; {len(cli)} CLI tokens observed."
    )
    return Spec(
        summary=summary,
        cli_surface=sorted(cli)[:60],
        behaviors=behaviors[:200],
        invariants=sorted(invariants),
        terms=terms,
    )


def ingest(root: Path) -> TaskUnderstanding:
    # Walked ONCE and shared -- census/build/harness previously each ran
    # their own full _walk_files(root) (and _detect_build did that per
    # marker, 11x over) -- ~13x redundant git-ls-files + is_file work on
    # every single ingest() call, found live 2026-07-22 while confirming
    # the ingest crash fix on this repo.
    files = list(_walk_files(root))
    census = _census_languages(files)
    language = next(iter(census), "unknown")
    build = _detect_build(root, files)
    harness, has_tests, test_files = _detect_harness(files)
    spec = _infer_spec(test_files, language)

    notes: list[str] = []
    oracle_name = "SYNTHESIZE"
    oracle_avail = False
    if language in _ORACLES:
        oracle = _ORACLES[language]
        oracle_name = oracle.name
        oracle_avail = oracle.available()
        if not oracle_avail:
            notes.append(f"oracle '{oracle.name}' toolchain missing: {oracle.install_hint}")
    else:
        notes.append(f"no registered oracle for '{language}' -- register one or synthesize.")
    if not has_tests:
        oracle_name = "SYNTHESIZE"
        notes.append(
            "no tests shipped -> synthesize_oracle() must manufacture ground "
            "truth (characterization / property / golden / contract) first."
        )

    hardware_profile = None
    if (
        detect_dialect_sources is not None
        and hw_profile_repo is not None
        and language in ("c", "cpp")
    ):
        try:
            found = detect_dialect_sources(root)
            if found:
                dialect, sources = found
                hp = hw_profile_repo(dialect, sources)
                hardware_profile = asdict(hp)
                if hp.critical_findings:
                    notes.append(
                        f"PRE-FLIGHT PROFILER: {hp.n_critical} CRITICAL hardware-boundary risk(s) "
                        f"detected across {hp.n_tensor_eligible}/{hp.n_call_sites} hardware-unit-"
                        f"eligible call sites for dialect '{dialect}' -- see hardware_profile."
                        f"critical_findings before starting any optimization work on this kernel."
                    )
                for w in hp.warnings:
                    notes.append(f"PRE-FLIGHT PROFILER warning: {w}")
        except Exception as e:
            notes.append(f"hardware profiler attempted but failed: {e}")

    return TaskUnderstanding(
        root=str(root),
        language=language,
        language_census=census,
        build_system=build,
        harness=harness,
        has_tests=has_tests,
        oracle=oracle_name,
        oracle_available=oracle_avail,
        spec=spec,
        notes=notes,
        hardware_profile=hardware_profile,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Determinex Universal Task Ingester")
    ap.add_argument("root", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    u = ingest(args.root)
    if args.json:
        print(json.dumps(asdict(u), indent=2))
        return 0
    print(f"=== INGEST: {u.root} ===")
    print(f"  language     : {u.language}   census={u.language_census}")
    print(f"  build_system : {u.build_system}")
    print(f"  harness      : {u.harness}   has_tests={u.has_tests}")
    print(f"  oracle       : {u.oracle}   available={u.oracle_available}")
    print(f"\n  SPEC: {u.spec.summary}")
    if u.spec.cli_surface:
        print(f"  CLI surface  : {' '.join(u.spec.cli_surface[:20])}")
    if u.spec.invariants:
        print("  invariants   :")
        for inv in u.spec.invariants:
            print(f"    - {inv}")
    if u.spec.behaviors:
        print(f"  behaviors    : ({len(u.spec.behaviors)} total, first 8)")
        for b in u.spec.behaviors[:8]:
            print(f"    - {b[:90]}")
    if u.notes:
        print("  notes:")
        for n in u.notes:
            print(f"    ! {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
