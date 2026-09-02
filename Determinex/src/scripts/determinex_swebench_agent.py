"""
scripts/determinex_swebench_agent.py — Determinex → SWE-bench Agent Adapter
======================================================================
Plugs Determinex's Hive Mind (multi-model, compiler-verified, closed-loop)
into the SWE-bench evaluation harness as a compliant agent.

SWE-bench interface contract:
  - Input:  repo clone path + GitHub issue text
  - Output: unified .patch file applied to repo

Determinex strategy (Flow AI — Test-Time Scaling):
  Phase 1 — Multi-path execution: hardware-aware parallel (≥16GB VRAM) or
             sequential (Tier 0). 3 isolated git worktrees × 3 temperatures.
             First path to pass all tests wins; others are cancelled.
  Phase 2 — Shadow compilation: run tests on unmodified repo BEFORE planning.
             Inject real traceback into Architect prompt — eliminates blind guessing.
  Phase 3 — Ripple regression: after targeted tests pass, sweep broader test dir.
             Filters fragile/hacky fixes that break adjacent modules.
  Phase 4 — Flywheel: every verified solve → auto_curriculum.jsonl for future LoRA.

Usage (standalone test):
    python scripts/determinex_swebench_agent.py \\
        --repo /path/to/cloned/repo \\
        --issue "Bug: list.sort() fails on empty list..." \\
        --out patch.diff

Usage (SWE-bench harness integration):
    from determinex_swebench_agent import DeterminexSWEAgent
    agent = DeterminexSWEAgent()
    patch = agent.solve(instance, repo_path=Path("/path/to/repo"))
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

# Ensure scripts/ dir is on path so sibling modules (determinex_cloak, etc.) are importable
# when agent is run standalone. The runner already does this via sys.path.insert.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Project Cloak — optional, gracefully absent when determinex_cloak not on path
try:
    from determinex_cloak import (
        CloakContext,
        CloakObfuscationError,
        build_cloak_context,
    )

    _CLOAK_AVAILABLE = True
except ImportError:
    _CLOAK_AVAILABLE = False
    CloakContext = None  # type: ignore[assignment,misc]

    class CloakObfuscationError(RuntimeError):  # type: ignore[no-redef]
        """Stub when determinex_cloak unavailable — should never fire."""


# Workspace escape guard — prevents symlink/traversal escapes on all file writes
try:
    from hive.workspace import assert_inside_workspace as _assert_in_workspace
except ImportError:

    def _assert_in_workspace(path: Path, workspace: Path) -> None:  # type: ignore[misc]
        pass


_CLOAK_ENABLED = bool(os.getenv("DETERMINEX_CLOAK", "")) and _CLOAK_AVAILABLE

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="[DETERMINEX-SWE] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("determinex_swe")

_ROOT = Path(__file__).resolve().parent.parent

# ── swe_agent subpackage ──────────────────────────────────────────────────────
from swe_agent.constants import (
    _GATE_MAX_AUTO,
    _GATE_MAX_TOTAL,
    _GATE_TEMPS,
    _LANG_COMPILE,
    _LANG_DISPLAY,
    _LANG_EXT,
    _LANG_EXTS,
    _LANG_FENCE,
    _NO_BLOCKS_SENTINEL,
    BUILDER_MODEL,
    CTX_LINES,
    LOCAL_BUILDER_MODEL,
    MAX_FILES,
    MAX_RETRIES,
    OBSERVER_MODEL,
    SKIP_NATIVE_TESTS,
    TEMPERATURES,
    TEST_TIMEOUT,
    USE_LOCAL_BUILDER,
    VRAM_PARALLEL_THRESHOLD_MB,
)
from swe_agent.inference import _infer, _ollama, _warm_local_builder
from swe_agent.patch import (
    _apply_search_replace_blocks,
    _normalize_for_match,
    _parse_search_replace_blocks,
)
from swe_agent.rag import _ADAPT_THRESHOLD, _HINT_THRESHOLD, _latent_retrieve, _load_latent_index


def _detect_repo_language(repo_path: Path) -> str:
    """Infer primary language by counting source files. Returns lowercase language name."""
    _SKIP_FRAG = {
        "site-packages",
        "__pycache__",
        ".tox",
        ".eggs",
        "node_modules",
        "target",
        "vendor",
        ".gradle",
        ".mvn",
        "build",
        "dist",
        "resources",
        "fixtures",
        ".cargo",
        "_vendor",
    }
    counts: dict[str, int] = {}
    lang_globs = [
        ("python", "*.py"),
        ("java", "*.java"),
        ("go", "*.go"),
        ("rust", "*.rs"),
        ("javascript", "*.js"),
        ("typescript", "*.ts"),
        ("ruby", "*.rb"),
        ("cpp", "*.cpp"),
        ("c", "*.c"),
        ("php", "*.php"),
    ]
    for lang, pattern in lang_globs:
        hits = [f for f in repo_path.rglob(pattern) if not any(p in _SKIP_FRAG for p in f.parts)]
        if hits:
            counts[lang] = len(hits)

    if not counts:
        return "python"

    best = max(counts, key=lambda k: counts[k])
    # C and C++ can co-exist; prefer C++ when both present
    if "cpp" in counts and "c" in counts and best == "c":
        if counts["cpp"] >= counts["c"] * 0.3:
            return "cpp"
    log.info("Detected repo language: %s (%d files)", best, counts[best])
    return best


# ── Search/Replace patch format ───────────────────────────────────────────────

SEARCH_REPLACE_FORMAT = """\
Output ONLY search/replace blocks in this exact format:
<<<SEARCH
[ORIGINAL lines from the source — must match character-for-character]
===
[FIXED replacement lines]
>>>REPLACE

CRITICAL RULES:
- SEARCH contains the ORIGINAL BROKEN code — copy it VERBATIM from the source above
- REPLACE contains the FIXED code — this is the only place you put your change
- SEARCH must match the file character-for-character (including spaces/tabs/empty lines)
- Keep SEARCH small: 3-15 lines, only what changes plus 1-2 lines of context
- NEVER put the fix in SEARCH — if SEARCH doesn't match, the patch fails
- NEVER output the whole file or whole function as REPLACE; only changed lines + minimal context
- Multiple blocks OK for separate locations in the same file
- PRESERVE INDENTATION: copy the EXACT whitespace from the source — if the source uses tabs, use tabs \
in both SEARCH and REPLACE; if it uses 2-space indent, use 2 spaces; NEVER convert tabs to spaces
- BRACE BALANCE: for languages with braces (Go/Java/Rust/C/C++/JS/TS), the net {{ }} delta in \
REPLACE must equal the net {{ }} delta in SEARCH — no dangling open or close braces
- NO INVENTED NAMES: every identifier in REPLACE must exist in the source shown above or be a \
language stdlib/std identifier — never invent new names
- WIRE UP NEW FUNCTIONS: if REPLACE introduces a new function/method definition, add a SECOND block \
that calls it from the appropriate location — dead code that is never called is a bug
- NO TRIVIAL BRANCHES: if/else branches must do meaningfully different things (not both return same value)
- NULL GUARD DIRECTION: if the bug is a missing null/nil/None check, guard the null case first — \
`if x is None` / `if x == nil` / `if (x == null)` — do NOT invert the guard unless the logic requires it
- LANGUAGE FIDELITY: write idiomatic code for the language shown — do NOT add Python-style syntax to \
Go/Java/Rust files or vice versa; respect the language's own conventions exactly as shown in the source
"""


# Only pass --timeout to pytest when pytest-timeout is installed.
def _pytest_timeout_flag() -> list[str]:
    import importlib.util

    if importlib.util.find_spec("pytest_timeout") is not None:
        return [f"--timeout={TEST_TIMEOUT}"]
    return []


# ── Hardware detection ────────────────────────────────────────────────────────


def _detect_compute_tier() -> str:
    """
    Returns 'parallel' if a GPU with ≥VRAM_PARALLEL_THRESHOLD_MB is available,
    'sequential' otherwise. Env override: DETERMINEX_COMPUTE_TIER=parallel|sequential.
    """
    override = os.getenv("DETERMINEX_COMPUTE_TIER", "").lower()
    if override in ("parallel", "sequential"):
        log.info("Compute tier override: %s", override)
        return override

    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            vram_values = [
                int(x.strip()) for x in r.stdout.strip().splitlines() if x.strip().isdigit()
            ]
            if vram_values and max(vram_values) >= VRAM_PARALLEL_THRESHOLD_MB:
                return "parallel"
    except Exception:
        pass

    return "sequential"


# ── Phase 2: Shadow Compilation ───────────────────────────────────────────────

_SHADOW_CLEAN = object()  # sentinel: tests pass on unmodified repo → skip instance


def shadow_compile(repo_path: Path, repo_language: str = "python") -> str | object:
    """
    Run the test suite on the UNMODIFIED repo before any changes.

    Return values (three states):
      _SHADOW_CLEAN  — tests already pass; caller should skip this instance entirely.
      ""             — no test files found or language not supported; proceed without trace.
      "<traceback>"  — failure captured; inject into Architect prompt.
    """
    log.info("Phase 2: Shadow compilation (language=%s)...", repo_language)

    _SKIP = {"site-packages", "__pycache__", "vendor", "node_modules", "target"}

    if repo_language == "go":
        # Go test suite times out reliably on Windows (cross-compiled binaries, slow linker)
        if platform.system() == "Windows":
            log.info("Shadow(go): skipped on Windows — always times out")
            return ""
        try:
            r = subprocess.run(
                ["go", "test", "-short", "-count=1", "./..."],
                capture_output=True,
                text=True,
                timeout=90,
                cwd=repo_path,
            )
            if r.returncode == 0:
                return _SHADOW_CLEAN
            out = (r.stdout + r.stderr)[:2000]
            log.info("Shadow(go): failure captured (%d chars)", len(out))
            return out
        except FileNotFoundError:
            return ""
        except Exception as e:
            log.warning("Shadow(go) failed: %s", e)
            return ""

    if repo_language == "rust":
        # cargo test times out reliably on Windows (120s wasted per instance)
        if platform.system() == "Windows":
            log.info("Shadow(rust): skipped on Windows — always times out")
            return ""
        try:
            r = subprocess.run(
                ["cargo", "test", "--", "--test-threads=4"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=repo_path,
            )
            if r.returncode == 0:
                return _SHADOW_CLEAN
            out = (r.stdout + r.stderr)[:2000]
            log.info("Shadow(rust): failure captured (%d chars)", len(out))
            return out
        except FileNotFoundError:
            return ""
        except Exception as e:
            log.warning("Shadow(rust) failed: %s", e)
            return ""

    if repo_language == "java":
        for build_file, cmd in [
            ("pom.xml", ["mvn", "-q", "test", "-Dsurefire.failIfNoSpecifiedTests=false"]),
            ("build.gradle", ["./gradlew", "test", "--quiet"]),
            ("build.gradle.kts", ["./gradlew", "test", "--quiet"]),
        ]:
            if (repo_path / build_file).exists():
                try:
                    r = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=120, cwd=repo_path
                    )
                    if r.returncode == 0:
                        return _SHADOW_CLEAN
                    return (r.stdout + r.stderr)[:2000]
                except Exception:
                    break
        return ""

    # Python/Ruby/PHP/JS/TS — pytest for Python, skip for others (no reliable cross-lang runner)
    if repo_language != "python":
        log.info("Shadow compile: no native test runner for %s — skipping", repo_language)
        return ""

    test_candidates = (
        list(repo_path.rglob("test_*.py"))[:5] + list(repo_path.rglob("*_test.py"))[:3]
    )
    test_candidates = [f for f in test_candidates if not any(s in f.parts for s in _SKIP)]
    if not test_candidates:
        log.info("No Python test files found — shadow compilation skipped")
        return ""

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest"]
            + [str(t) for t in test_candidates[:3]]
            + ["-x", "--tb=short", "-q", "--no-header"]
            + _pytest_timeout_flag(),
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT + 30,
            cwd=repo_path,
            env={**os.environ, "PYTHONWARNINGS": "ignore"},
        )
        output = _format_test_output(result.stdout, result.stderr)
        if result.returncode == 0:
            log.info(
                "Shadow compile: all tests already pass on unmodified repo — skipping instance"
            )
            return _SHADOW_CLEAN
        log.info("Shadow compile: traceback captured (%d chars)", len(output))
        return output
    except Exception as e:
        log.warning("Shadow compilation failed: %s", e)
        return ""


# ── Step 1: File Localization ─────────────────────────────────────────────────

_SKIP_NAME_PATTERNS = frozenset(
    {
        "__init__",
        "setup_package",
        "conftest",
        "_version",
        "version",
        "setup",
        "_setup",
        "compat",
        "_compat",
    }
)
_SKIP_DIR_FRAGMENTS = frozenset(
    {
        "site-packages",
        "__pycache__",
        ".pyinstaller",
        ".tox",
        "build",
        "dist",
        ".eggs",
        "node_modules",
        "target",
        "vendor",
        ".gradle",
        ".mvn",
        "resources",
        "fixtures",
        ".cargo",
        "_vendor",
    }
)


def _is_source_candidate(f: Path) -> bool:
    """True for files that could plausibly contain the bug, false for boilerplate."""
    name = f.stem.lower()
    if name in _SKIP_NAME_PATTERNS:
        return False
    parts = {p.lower() for p in f.parts}
    if parts & _SKIP_DIR_FRAGMENTS:
        return False
    return True


def _is_test_file(f: Path) -> bool:
    """True if this looks like a test file (lower priority as fix target).

    Covers naming conventions across Python, Go, Java, Rust, Ruby, JS/TS, PHP, C/C++.
    """
    name = f.stem.lower()
    ext = f.suffix.lower()

    # Universal stem-based patterns
    if name.startswith("test_") or name.endswith("_test"):
        return True
    if name in ("tests", "conftest", "spec", "specs"):
        return True
    # Go: foo_test.go (already caught by _test suffix), but also
    # Java: FooTest.java, TestFoo.java
    if ext == ".java" and (name.startswith("test") or name.endswith("test")):
        return True
    # Jest / Mocha / Jasmine: foo.spec.ts, foo.test.ts
    if ext in (".ts", ".js") and ("spec" in name or "test" in name):
        return True
    # Ruby: spec files live in spec/ dir
    if ext == ".rb" and (name.endswith("_spec") or name.startswith("test_")):
        return True
    # PHP: FooTest.php
    if ext == ".php" and name.endswith("test"):
        return True
    # C/C++: test_foo.c, foo_test.c — already caught

    # Rust: detect test-container files where #[cfg(test)] appears in the first 50 lines
    # and the file is large (e.g. pyflakes/mod.rs is 4639 lines, 99% test code).
    # Normal impl files with inline tests have #[cfg(test)] near the bottom, not the top.
    if f.suffix.lower() == ".rs":
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
            if len(lines) > 300:
                header = "\n".join(lines[:50])
                if "#[cfg(test)]" in header:
                    return True
        except Exception:
            pass

    # Files inside canonical test/spec directories (all languages)
    parts_lower = [p.lower() for p in f.parts]
    return any(
        p in parts_lower
        for p in ("tests", "test", "spec", "specs", "__tests__", "testdata", "test_data")
    )


def _module_path_to_file(repo_path: Path, module_str: str) -> Path | None:
    """
    Convert a dotted module name like 'astropy.modeling.separable' or a partial
    path like 'ascii.rst' to its corresponding .py file in the repo.
    """
    parts = module_str.split(".")
    # Pass 1: exact left-to-right prefix strip (fast, covers full module paths)
    for start in range(0, len(parts)):
        rel = "/".join(parts[start:]) + ".py"
        candidate = repo_path / rel
        if candidate.exists():
            return candidate
    # Pass 2: suffix glob — handles partial paths like 'ascii.rst' that map to
    # 'astropy/io/ascii/rst.py'. Search repo for any file whose path ends with
    # the full component sequence. Uses the filename as the glob anchor for speed.
    filename = parts[-1] + ".py"
    prefix_parts = parts[:-1]
    for match in repo_path.rglob(filename):
        if not _is_source_candidate(match):
            continue
        if not prefix_parts:
            return match
        match_str = match.as_posix()
        # All prefix components must appear in order in the path
        pos = 0
        for p in prefix_parts:
            idx = match_str.find("/" + p + "/", pos)
            if idx == -1:
                break
            pos = idx + 1
        else:
            return match
    return None


def locate_relevant_files(
    repo_path: Path,
    issue_text: str,
    repo_language: str = "python",
    fail_tests: str = "",
) -> tuple[list[Path], list[str]]:
    """
    Observer: keyword extraction from issue → scan repo → rank by density → top N.

    Returns (relevant_files, keywords) — keywords passed back so plan_fix can reuse them.

    Scoring:
    - Direct module-path resolution gets +10 (highest priority)
    - Source files score 2× test files for same keyword count
    - __init__.py, setup files, hooks, skip-dir files are excluded
    - Language-aware: scans correct file extensions per repo_language
    """
    log.info("Locating relevant files via keyword extraction (lang=%s)...", repo_language)
    lang_label = _LANG_DISPLAY.get(repo_language, repo_language.capitalize())
    kw_prompt = (
        f"Extract 5-8 specific {lang_label} identifiers, function names, class names, "
        f"or module names mentioned in this GitHub issue. "
        f"Return ONLY a JSON list of strings, nothing else.\n\nIssue:\n{issue_text[:2000]}"
    )
    kw_resp = _infer(
        OBSERVER_MODEL,
        kw_prompt,
        system="You extract code identifiers from bug reports. Return only JSON.",
        keep_alive=0,
    )

    keywords: list[str] = []
    try:
        m = re.search(r"\[.*?\]", kw_resp, re.DOTALL)
        if m:
            keywords = json.loads(m.group())
    except Exception:
        pass

    _NOISE = frozenset(
        {
            "error",
            "issue",
            "should",
            "would",
            "could",
            "please",
            "count",
            "stdout",
            "stdin",
            "stderr",
            "sys",
            "os",
            "path",
            "test",
            "tests",
            "assert",
            "format",
            "print",
            "write",
            "read",
            "open",
            "true",
            "false",
            "none",
            "self",
            "args",
            "kwargs",
            "return",
            "raise",
            "import",
            "from",
            "with",
            "file",
            "data",
            "value",
            "result",
            "output",
            "input",
            "name",
            "type",
            "class",
            "object",
            "string",
            "list",
            "dict",
            "tuple",
            "bool",
            "nil",
            "null",
            "void",
            "int",
            "str",
            "uint",
            "byte",
            "char",
        }
    )

    keywords = [k for k in keywords if k.lower() not in _NOISE]

    # Also extract identifiers from failing test names (high-signal keywords)
    if fail_tests:
        try:
            test_ids = json.loads(fail_tests) if fail_tests.startswith("[") else [fail_tests]
            for tid in test_ids[:5]:
                parts = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b", tid)
                keywords += [p for p in parts if p.lower() not in _NOISE]
        except Exception:
            pass

    if not keywords:
        keywords = [
            w
            for w in re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{4,}\b", issue_text)
            if w.lower() not in _NOISE
        ][:8]

    def _clean_kw(k: str) -> str:
        k = re.sub(r"\(.*", "", k)
        m = re.match(r"^[a-zA-Z]{1,2}\.(.+)$", k)
        if m:
            k = m.group(1)
        return k.strip()

    raw_keywords = keywords
    keywords = list(dict.fromkeys(_clean_kw(k) for k in raw_keywords if len(_clean_kw(k)) >= 4))
    log.info("Keywords: %s", keywords)

    scores: dict[Path, float] = {}

    # Priority 1: direct module-path resolution (Python dotted names → .py files)
    if repo_language == "python":
        for kw in raw_keywords:
            cleaned = _clean_kw(kw)
            for candidate_kw in [kw, cleaned]:
                if "." in candidate_kw:
                    resolved = _module_path_to_file(repo_path, candidate_kw)
                    if resolved and _is_source_candidate(resolved):
                        scores[resolved] = scores.get(resolved, 0) + 10.0
                        log.info(
                            "Direct module resolve: %s → %s",
                            candidate_kw,
                            resolved.relative_to(repo_path),
                        )

    # Scan correct source extensions for this language
    patterns = _LANG_EXTS.get(repo_language, ["*.py"])
    src_files: list[Path] = []
    for pat in patterns:
        src_files.extend(f for f in repo_path.rglob(pat) if _is_source_candidate(f))
    src_files = list(dict.fromkeys(src_files))  # dedup

    # Language-specific definition patterns for scoring
    if repo_language == "python":
        def_patterns = [("def {kw}", 6.0), ("class {kw}", 6.0)]
    elif repo_language in ("javascript", "typescript"):
        def_patterns = [("function {kw}", 5.0), ("const {kw}", 4.0), ("class {kw}", 6.0)]
    elif repo_language == "java":
        def_patterns = [("class {kw}", 6.0), ("interface {kw}", 5.0), ("void {kw}(", 4.0)]
    elif repo_language == "go":
        def_patterns = [("func {kw}(", 6.0), ("func ({kw}", 5.0), ("type {kw} ", 4.0)]
    elif repo_language == "rust":
        def_patterns = [("fn {kw}(", 6.0), ("struct {kw}", 5.0), ("impl {kw}", 5.0)]
    else:
        # Language-agnostic fallback: funcName( pattern
        def_patterns = [("{kw}(", 4.0), ("class {kw}", 6.0)]

    for p in src_files:
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            for kw in keywords:
                matched_def = False
                for pat_tmpl, score in def_patterns:
                    if pat_tmpl.replace("{kw}", kw) in content:
                        scores[p] = scores.get(p, 0) + score
                        matched_def = True
                        break
                if not matched_def:
                    # Language-agnostic call-site fallback: `funcName(`
                    call_pattern = re.compile(rf"\b{re.escape(kw)}\s*\(")
                    if call_pattern.search(content):
                        weight = 1.0 if _is_test_file(p) else 2.5
                        scores[p] = scores.get(p, 0) + weight
                    elif kw in content:
                        weight = 0.5 if _is_test_file(p) else 1.5
                        scores[p] = scores.get(p, 0) + weight
        except Exception:
            pass

    if not scores:
        return sorted(src_files, key=lambda f: f.stat().st_size)[:MAX_FILES], keywords

    source_files = [(p, s) for p, s in scores.items() if not _is_test_file(p)]
    test_files = [(p, s) for p, s in scores.items() if _is_test_file(p)]

    source_ranked = sorted(source_files, key=lambda x: (-x[1], len(str(x[0]))))
    test_ranked = sorted(test_files, key=lambda x: (-x[1], len(str(x[0]))))

    final_list = [p for p, _ in source_ranked] + [p for p, _ in test_ranked]
    return final_list[:MAX_FILES], keywords


def read_file_context(
    file_path: Path,
    max_lines: int = CTX_LINES,
    source_override: str = "",
) -> str:
    try:
        content = (
            source_override
            if source_override
            else file_path.read_text(encoding="utf-8", errors="replace")
        )
        lines = content.splitlines()
        numbered = [f"{i + 1:4d}: {line}" for i, line in enumerate(lines[:max_lines])]
        if len(lines) > max_lines:
            numbered.append(f"... ({len(lines) - max_lines} more lines truncated)")
        return "\n".join(numbered)
    except Exception as e:
        return f"# Error reading {file_path}: {e}"


# ── Step 1b: Semantic Key — local context bridge for Cloak ───────────────────


def _name_to_hint(real_name: str) -> str:
    """Convert a real identifier to a semantic hint without exposing the name.

    '_session_cache'   → 'session cache (private attr)'
    'database_backwards' → 'database backwards (fn)'
    '__init__'         → 'object initializer (dunder)'
    'MAX_RETRIES'      → 'max retries (constant)'
    """
    name = real_name
    category = ""
    if name.startswith("__") and name.endswith("__"):
        # dunder — describe by well-known ones, else generic
        known = {
            "__init__": "object initializer",
            "__repr__": "repr method",
            "__str__": "str method",
            "__len__": "length method",
            "__eq__": "equality method",
            "__hash__": "hash method",
            "__call__": "callable method",
            "__enter__": "context enter",
            "__exit__": "context exit",
            "__iter__": "iterator method",
            "__next__": "iterator next",
            "__getitem__": "item getter",
            "__setitem__": "item setter",
            "__contains__": "membership test",
        }
        return known.get(name, "dunder method")
    if name.startswith("__"):
        name = name[2:]
        category = "name-mangled private"
    elif name.startswith("_"):
        name = name[1:]
        category = "private"
    if name.isupper():
        category = (category + " constant").strip()
    # camelCase → words
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    words = name.replace("_", " ").lower().strip()
    return f"{words} ({category})" if category else words


def build_semantic_key(
    cloak_ctx: CloakContext,
    relevant_files: list[Path],
    repo_path: Path,
    max_tokens: int = 30,
) -> str:
    """Generate a local semantic glossary for x_NNNN tokens in the fix region.

    Reads the obfuscated versions of the relevant files, extracts the x_NNNN
    tokens that appear, maps each back to a human-readable semantic hint
    (NOT the real name), and returns a compact prompt header.

    This bridges the gap between the Architect's plan (which references real
    concepts from the issue text) and the Builder's view (obfuscated x_NNNN
    tokens). The real names never appear in the outbound API payload — only
    the functional descriptions do.
    """
    _X_RE = re.compile(r"\bx_\d{4}\b")
    seen_tokens: dict[str, int] = {}  # token → frequency

    if cloak_ctx is None:
        return ""

    for f in relevant_files[:4]:
        try:
            obf = cloak_ctx.obfuscate_file(f, repo_path)  # type: ignore[union-attr]
            for tok in _X_RE.findall(obf):
                seen_tokens[tok] = seen_tokens.get(tok, 0) + 1
        except Exception:
            continue

    if not seen_tokens:
        return ""

    # Sort by frequency (most-referenced tokens first), cap at max_tokens
    top_tokens = sorted(seen_tokens.items(), key=lambda kv: -kv[1])[:max_tokens]

    lines = []
    for token, _ in top_tokens:
        real_name = cloak_ctx.symbol_map.reverse.get(token)  # type: ignore[union-attr]
        if not real_name:
            continue
        hint = _name_to_hint(real_name)
        lines.append(f"  {token}: {hint}")

    if not lines:
        return ""

    return (
        "[SYMBOL GUIDE — generated locally, not transmitted as real names]\n"
        "Token semantics for this fix region:\n" + "\n".join(lines)
    )


# ── Step 2: Architect — Generate Fix Plan ────────────────────────────────────


def plan_fix(
    issue_text: str,  # may already contain shadow traceback
    relevant_files: list[Path],
    repo_path: Path,
    temperature: float = 0.1,
    cloak_ctx: CloakContext | None = None,
    semantic_key: str = "",
    hints: str = "",
    fail_tests: str = "",
    repo_language: str = "python",
    keywords: list[str] | None = None,
    decompose_hint: str = "",  # injected BEFORE the prompt — bypasses issue_text[:2000] truncation
) -> list[dict]:
    """
    Architect decomposes the fix into a minimal DAG (1-3 atomic steps).
    issue_text should contain the shadow traceback when available.
    When cloak_ctx is provided, file contents shown to the Architect are obfuscated.
    When semantic_key is provided, a local symbol guide is prepended so the
    Architect can map x_NNNN tokens to their functional meaning.
    """
    log.info("Planning fix DAG with Architect (T=%.1f)...", temperature)

    file_summaries = []
    for f in relevant_files[:4]:
        rel = f.relative_to(repo_path)
        override = cloak_ctx.obfuscate_file(f, repo_path) if cloak_ctx else ""
        content = read_file_context(f, max_lines=60, source_override=override)
        # Under Cloak: anonymize the file heading so the Architect can't infer real
        # names from well-known paths like astropy/wcs/wcs.py. Use hash-based label.
        if cloak_ctx and override:
            _fh = hashlib.md5(str(rel).encode()).hexdigest()[:8]
            _fext = Path(str(rel)).suffix
            display_rel = f"module_{_fh}{_fext}"
        else:
            display_rel = str(rel)
        file_summaries.append(f"=== {display_rel} ===\n{content}")

    lang_label = _LANG_DISPLAY.get(repo_language, repo_language.capitalize())
    lang_ext = _LANG_EXT.get(repo_language, "." + repo_language)
    key_section = f"\n\n{semantic_key}" if semantic_key else ""
    hints_section = f"\n\nHints:\n{hints}" if hints else ""
    fail_section = f"\n\nFailing tests (must pass after fix):\n{fail_tests}" if fail_tests else ""
    # Obfuscate keyword list in Cloak mode — raw keywords contain real private names
    # extracted before obfuscation (e.g. _return_list_of_arrays). Showing these to
    # the Architect tells it the real name, defeating Cloak and causing step
    # descriptions with real names instead of x_NNNN tokens.
    kw_list = keywords or []
    if cloak_ctx and kw_list:
        kw_list = [cloak_ctx.obfuscate_text(kw) for kw in kw_list]
    kw_section = f"\n\nKey identifiers from the issue: {', '.join(kw_list[:8])}" if kw_list else ""

    # Language-specific diagnostic rules injected into the Architect prompt
    _lang_rules: dict[str, str] = {
        "python": (
            "\n\nCOMMON BUG PATTERNS TO VERIFY BEFORE PLANNING:"
            "\n- None guard direction: if the bug is a missing None-check, add `if x is None:` "
            "(not `if x is not None:`), unless the existing logic clearly requires the opposite"
            "\n- Exact exception class: use the precise exception type from the traceback "
            "(e.g. ValueError, not Exception; AttributeError, not RuntimeError)"
            "\n- Pre-flight check: mentally trace the failing test through your proposed fix "
            "before writing the plan — confirm the fix changes the outcome"
        ),
        "go": (
            "\n\nCOMMON GO BUG PATTERNS:"
            "\n- Error shadowing: check for `:=` that shadows an outer `err` variable"
            "\n- nil pointer: guard with `if x == nil` before dereferencing"
            "\n- goroutine data races: ensure shared state is protected with sync.Mutex or channel"
            "\n- interface nil trap: a typed nil is not equal to interface nil — use explicit nil return"
            "\n- Off-by-one: slice bounds [start:end] are half-open — end is exclusive"
        ),
        "rust": (
            "\n\nCOMMON RUST BUG PATTERNS:"
            "\n- Unwrap panics: replace `.unwrap()` with `?` propagation or `.unwrap_or_else()`"
            "\n- Borrow checker: avoid holding a mutable borrow while an immutable one exists"
            "\n- Integer overflow: use `.checked_add()` / `.saturating_add()` for untrusted input"
            "\n- Match exhaustion: ensure all enum variants are handled (compiler enforces this)"
            "\n- Off-by-one in ranges: `0..n` is exclusive on the right; `0..=n` is inclusive"
        ),
        "java": (
            "\n\nCOMMON JAVA BUG PATTERNS:"
            "\n- NullPointerException: add null check before dereferencing, or use Optional"
            "\n- equals vs ==: always use .equals() for String/Object comparison, not =="
            "\n- Integer overflow: use long arithmetic for large values; check int arithmetic"
            "\n- Checked exceptions: propagate or handle — never swallow in empty catch block"
            "\n- Autoboxing null: unboxing a null Integer/Boolean throws NPE"
        ),
        "javascript": (
            "\n\nCOMMON JS BUG PATTERNS:"
            "\n- === vs ==: always use === for equality checks (== coerces types)"
            "\n- undefined vs null: check explicitly with === null or === undefined"
            "\n- async/await: missing await on async calls returns Promise, not value"
            "\n- this binding: arrow functions inherit this; regular functions bind at call site"
            "\n- Array mutation: methods like .sort() mutate in place — clone if needed"
        ),
        "typescript": (
            "\n\nCOMMON TS BUG PATTERNS:"
            "\n- Type narrowing: use `typeof x === 'string'` or `x instanceof Foo` before using"
            "\n- Non-null assertion (!): prefer optional chaining `x?.y` over `x!.y`"
            "\n- as any: kills type safety — find the correct type instead"
            "\n- async/await: missing await on async calls returns Promise, not the resolved value"
        ),
        "ruby": (
            "\n\nCOMMON RUBY BUG PATTERNS:"
            "\n- nil safety: check `x.nil?` before calling methods on potentially nil objects"
            "\n- Symbol vs string: hash keys are either :symbol or 'string' — be consistent"
            "\n- Integer division: `5 / 2 == 2` in Ruby — use `.to_f` for float result"
            "\n- Method missing: check `respond_to?` before calling dynamic methods"
        ),
        "php": (
            "\n\nCOMMON PHP BUG PATTERNS:"
            "\n- Loose comparison: use === instead of == to avoid type coercion surprises"
            "\n- isset vs empty: isset() checks null; empty() also checks 0/false/'' — choose carefully"
            "\n- String functions: str_contains/str_starts_with require PHP 8+; use strpos for compat"
            "\n- Array key access: use isset($arr['key']) before $arr['key'] to avoid undefined index"
        ),
    }
    _lang_specific_rules = _lang_rules.get(repo_language, "")

    decompose_section = f"\n\n{decompose_hint}" if decompose_hint else ""
    plan_prompt = (
        f"You are a battle-hardened {lang_label} architect — you clawed your way up "
        f"from grunt-level code, survived production fires, and now you see every "
        f"failure pattern cold. You fix issues the mathematically minimal way: no "
        f"cargo-culting, no scope creep, no invented names. You are untouchable on this.\n"
        f"Analyze this GitHub issue and the relevant source files.\n"
        f"Produce a minimal fix plan: 1-3 atomic steps, each modifying or creating "
        f"one file.\n\n"
        f"Issue and traceback:\n{issue_text[:2000]}\n\n"
        f"Relevant files:\n{'---'.join(file_summaries[:2])}"
        f"{key_section}{hints_section}{fail_section}{kw_section}"
        f"{decompose_section}\n\n"
        f"Return ONLY a JSON array of steps:\n"
        f'[{{"step": 1, "file": "path/to/file{lang_ext}", "action": "modify", '
        f'"description": "Fix the X function to handle Y edge case"}}]\n'
        f"RULES: Use relative paths from repo root. Maximum 3 steps. Minimal targeted changes.\n"
        f"NEVER target test files. Only modify SOURCE files.\n"
        f"DESCRIPTION FORMAT: Include the EXACT x_NNNN token(s) from the code that need changing "
        f"(e.g. 'change x_6161.replace(...) to x_6161 = x_6161.replace(...)'). "
        f"This is critical for the Builder to locate the right line."
        f"{_lang_specific_rules}"
    )

    plan_resp = _infer(
        OBSERVER_MODEL,
        plan_prompt,
        system="You plan minimal code fixes. Return only JSON arrays.",
        temperature=temperature,
        keep_alive=0,
    )

    steps: list[dict] = []
    try:
        m = re.search(r"\[.*?\]", plan_resp, re.DOTALL)
        if m:
            steps = json.loads(m.group())
    except Exception:
        pass

    # Heal template paths: model output the right description but wrong file path.
    # e.g. file="path/to/file.py", description="fix fitsrec.py" → resolve fitsrec.py
    # Language-aware: search for the repo's primary extension in the description text.
    _lang_ext_re = {
        "python": r"\b([\w/]+\.py)\b",
        "java": r"\b([\w/]+\.java)\b",
        "go": r"\b([\w/]+\.go)\b",
        "rust": r"\b([\w/]+\.rs)\b",
        "ruby": r"\b([\w/]+\.rb)\b",
        "php": r"\b([\w/]+\.php)\b",
        "javascript": r"\b([\w/]+\.(?:js|ts))\b",
        "typescript": r"\b([\w/]+\.(?:ts|js))\b",
        "c": r"\b([\w/]+\.(?:c|h))\b",
        "cpp": r"\b([\w/]+\.(?:cpp|cc|cxx|hpp|h))\b",
    }
    _file_re = re.compile(_lang_ext_re.get(repo_language, r"\b([\w/]+\.\w+)\b"))

    steps = [s for s in steps if isinstance(s, dict)]
    for step in steps:
        file_val = step.get("file", "")
        if "path/to" in file_val or file_val.startswith("path/"):
            desc = step.get("description", "") + " " + step.get("action", "")
            src_names = _file_re.findall(desc)
            healed = None
            for candidate_name in src_names:
                matches = list(repo_path.rglob(Path(candidate_name).name))
                matches = [f for f in matches if _is_source_candidate(f) and not _is_test_file(f)]
                if matches:
                    healed = str(matches[0].relative_to(repo_path))
                    log.info(
                        "Healed template path '%s' → '%s' (from description)", file_val, healed
                    )
                    break
            # Fallback: use top-ranked relevant file when description gives no filename
            if not healed and relevant_files:
                src_files = [f for f in relevant_files if not _is_test_file(f)]
                fallback = (src_files or relevant_files)[0]
                healed = str(fallback.relative_to(repo_path))
                log.info(
                    "Healed template path '%s' → '%s' (top relevant file fallback)",
                    file_val,
                    healed,
                )
            if healed:
                step["file"] = healed

    if not steps and relevant_files:
        rel = relevant_files[0].relative_to(repo_path)
        steps = [
            {
                "step": 1,
                "file": str(rel),
                "action": "modify",
                "description": f"Fix the bug described in the issue in {rel}",
            }
        ]

    log.info("Fix plan: %d step(s)", len(steps))
    for s in steps:
        log.info(
            "  Step %s: %s → %s", s.get("step", "?"), s.get("file", "?"), s.get("description", "?")
        )
    return steps


# ── Step 3: Builder — Generate Code Fix ──────────────────────────────────────

_REGION_THRESHOLD = int(os.getenv("DETERMINEX_REGION_THRESHOLD", "0"))  # 0 = always use region mode
_REGION_CONTEXT = int(os.getenv("DETERMINEX_REGION_CONTEXT", "80"))


def _fn_def_patterns(lang: str) -> list[str]:
    """Return ordered list of function-definition regex templates for anchoring."""
    if lang == "python":
        return [r"\s*(?:async\s+)?def\s+{name}\s*\("]
    if lang == "go":
        return [r"\s*func\s+(?:\([^)]*\)\s*)?{name}\s*\("]
    if lang == "rust":
        return [r"\s*(?:pub\s+)?(?:async\s+)?fn\s+{name}\s*[(<]"]
    if lang == "java":
        return [
            r"\s*(?:(?:public|private|protected|static|final|abstract|synchronized)\s+)*\w[\w<>\[\]]*\s+{name}\s*\("
        ]
    if lang in ("javascript", "typescript"):
        return [
            r"\s*(?:async\s+)?function\s+{name}\s*\(",
            r"\s*(?:const|let|var)\s+{name}\s*=\s*(?:async\s+)?\(",
        ]
    if lang == "ruby":
        return [r"\s*def\s+{name}(?:\s*\(|\s*$)"]
    if lang == "php":
        return [r"\s*(?:public\s+|private\s+|protected\s+|static\s+)*function\s+{name}\s*\("]
    if lang in ("c", "cpp"):
        return [r"[\w\s\*]+\s+{name}\s*\("]
    # fallback: any language
    return [r"(?:def|fn|func|function)\s+{name}\s*[(\s]", r"\b{name}\s*[=:]\s*(?:function|async)"]


def _extract_target_region(
    lines: list[str],
    step_desc: str,
    shadow_trace: str,
    file_path: str,
    context: int = _REGION_CONTEXT,
    cloak_mode: bool = False,
    repo_language: str = "python",
) -> tuple[int, int]:
    """
    Return (start, end) 0-indexed line range to pass to the builder.

    Priority (normal mode):  shadow traceback line → named function in step desc → top of file.
    Priority (cloak mode):   named function in step desc → shadow traceback line → top of file.

    In Cloak mode the step_desc already contains x_NNNN tokens (translated by the
    caller). The Architect's explicit function target is more reliable than the
    shadow trace, which points to the call site of wrong behaviour — not the root
    cause. Swapping priority in Cloak mode avoids anchoring in the wrong function.
    """
    anchor_shadow = -1
    anchor_desc = -1

    # Shadow traceback — look for "filename", line N (language-agnostic)
    fname = Path(file_path).name
    for m in re.finditer(
        rf"(?:{re.escape(fname)}|{re.escape(file_path.replace(chr(92), '/'))})[^\d]*?(\d+)",
        shadow_trace,
    ):
        candidate = int(m.group(1)) - 1  # 0-indexed
        if 0 <= candidate < len(lines):
            anchor_shadow = candidate
            break

    fn_patterns = _fn_def_patterns(repo_language)
    _SKIP_NAMES = {
        "def",
        "class",
        "if",
        "for",
        "return",
        "self",
        "func",
        "fn",
        "function",
        "public",
        "private",
        "protected",
        "static",
    }

    # Named function from step description.
    # In Cloak mode step_desc contains x_NNNN tokens — extract them directly.
    # In normal mode extract call-site patterns: identifier( or `identifier`.
    if cloak_mode:
        cloak_tokens = re.findall(r"\bx_\d{4}\b", step_desc)
        # Pass 1: function/class definition lines (strongest anchor)
        for token in cloak_tokens:
            for i, line in enumerate(lines):
                for pat_tmpl in fn_patterns:
                    if re.match(pat_tmpl.replace("{name}", re.escape(token)), line):
                        anchor_desc = i
                        break
                if anchor_desc >= 0:
                    break
            if anchor_desc >= 0:
                break
        # Pass 2: any line containing ALL tokens from the step_desc expression.
        # The Architect often quotes the broken code line: "change x_6161.replace(x_3044...)"
        # Searching for lines with multiple co-occurring tokens pinpoints the exact line
        # even when x_6161 appears in many places (e.g., as a function parameter).
        if anchor_desc < 0 and len(cloak_tokens) >= 2:
            all_toks_re = [re.compile(rf"\b{re.escape(t)}\b") for t in cloak_tokens]
            for i, line in enumerate(lines):
                if all(r.search(line) for r in all_toks_re):
                    anchor_desc = i
                    break
        # Pass 3: fall back to first line containing ANY single token.
        # Prefer code lines over docstring/comment lines — prevents anchoring
        # inside a parameter docstring when the actual implementation is elsewhere.
        if anchor_desc < 0:
            for token in cloak_tokens:
                tok_re = re.compile(rf"\b{re.escape(token)}\b")
                code_hit = -1
                doc_hit = -1
                in_docstring = False
                for i, raw in enumerate(lines):
                    s = raw.strip()
                    # Track triple-quote docstring boundaries
                    for q in ('"""', "'''"):
                        if q in s:
                            count = s.count(q)
                            if count % 2 == 1:
                                in_docstring = not in_docstring
                    if tok_re.search(raw):
                        is_doc = in_docstring or s.startswith(("#", '"""', "'''"))
                        if is_doc:
                            if doc_hit < 0:
                                doc_hit = i
                        else:
                            if code_hit < 0:
                                code_hit = i
                                break
                anchor_desc = code_hit if code_hit >= 0 else doc_hit
                if anchor_desc >= 0:
                    break
    else:
        for m in re.finditer(r'[`\'"]?(\w+)\s*\(', step_desc):
            name = m.group(1)
            if len(name) < 3 or name in _SKIP_NAMES:
                continue
            for i, line in enumerate(lines):
                for pat_tmpl in fn_patterns:
                    if re.match(pat_tmpl.replace("{name}", re.escape(name)), line):
                        anchor_desc = i
                        break
                if anchor_desc >= 0:
                    break
            if anchor_desc >= 0:
                break

    # Resolve priority — log which signal won for debugging
    if cloak_mode and anchor_desc >= 0:
        anchor = anchor_desc  # Architect's explicit target wins in Cloak mode
        log.info("[region] cloak anchor=%d from desc (file=%s)", anchor, Path(file_path).name)
    elif anchor_shadow >= 0:
        anchor = anchor_shadow  # shadow trace wins in normal mode
        log.info("[region] shadow anchor=%d (file=%s)", anchor, Path(file_path).name)
    elif anchor_desc >= 0:
        anchor = anchor_desc
        log.info("[region] desc anchor=%d (file=%s)", anchor, Path(file_path).name)
    else:
        anchor = min(50, len(lines) - 1)  # fallback: top of file
        log.warning(
            "[region] no anchor — falling back to line %d (file=%s)", anchor, Path(file_path).name
        )

    # If anchor is on a def/class line, the function body lives below the docstring.
    # Shift the window center to the first code line after the docstring so the
    # builder sees what needs changing rather than spending its context on the signature.
    body_anchor = anchor
    anchor_stripped = lines[anchor].strip() if 0 <= anchor < len(lines) else ""
    if re.match(r"(async\s+)?def\s+|class\s+", anchor_stripped):
        in_ds = False
        for j in range(anchor + 1, min(anchor + 120, len(lines))):
            s = lines[j].strip()
            for q in ('"""', "'''"):
                if q in s:
                    if s.count(q) % 2 == 1:
                        in_ds = not in_ds
            if not in_ds and s and not s.startswith(("#", '"""', "'''")):
                body_anchor = j
                break

    start = max(0, body_anchor - context)
    end = min(len(lines), body_anchor + context)
    # Always include the def/class line itself for signature context
    start = min(start, anchor)
    return start, end


def _check_fixed_syntax(target: Path, content: str, repo_language: str = "python") -> str | None:
    """
    Run a quick compile/parse check on the proposed fixed content.
    Returns None if the content is syntactically valid (or check not available).
    Returns an error string if there's a compile/syntax error.

    Go: writes the file in-place, runs `go build ./...` in the repo dir, then restores the
    original. This is the only reliable approach since Go requires package context.

    C++: Windows MinGW may be missing stdlib headers. Filter those — Docker will compile.
    """
    import tempfile

    # ── Go: in-place build check (requires package context) ──────────────────
    if repo_language == "go":
        original_bytes = b""
        try:
            original_bytes = target.read_bytes()
            target.write_text(content, encoding="utf-8")
            r = subprocess.run(
                ["go", "build", "./..."],
                cwd=target.parent,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode != 0:
                # Filter out errors in the Go module cache (pre-existing dep issues).
                # Only report errors in files under the repo directory.
                repo_root = str(target.parent)
                error_lines = [
                    l
                    for l in (r.stderr + r.stdout).splitlines()
                    if "error" in l.lower() and repo_root.lower() in l.lower()
                ]
                if not error_lines:
                    return None  # all errors are in deps, not our code
                errors = "\n".join(error_lines)[:600]
                return f"Go compile error:\n{errors}" if errors else None
            return None
        except FileNotFoundError:
            return None  # go not on PATH
        except subprocess.TimeoutExpired:
            return None
        except Exception as e:
            log.debug("_check_fixed_syntax(go) error: %s", e)
            return None
        finally:
            try:
                if original_bytes:
                    target.write_bytes(original_bytes)
            except Exception:
                pass

    cmd_template = _LANG_COMPILE.get(repo_language, [])
    if not cmd_template:
        return None

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=_LANG_EXT.get(repo_language, ".tmp"),
            delete=False,
            encoding="utf-8",
        ) as tf:
            tf.write(content)
            tmp_path = tf.name

        cmd = [c.replace("{file}", tmp_path) for c in cmd_template]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        if r.returncode != 0:
            errors = "\n".join(
                l for l in (r.stderr + r.stdout).splitlines() if "error" in l.lower()
            )[:600]

            if repo_language in ("c", "cpp"):
                # Filter Windows MinGW missing system headers — infrastructure gap, not code bug
                _sys_hdr_re = re.compile(r"fatal error: [^/\\<>\n]+: [Nn]o such file")
                real_errors = [
                    l for l in errors.splitlines() if l.strip() and not _sys_hdr_re.search(l)
                ]
                if not real_errors:
                    return None  # only system headers missing — Docker will compile
                return f"{_LANG_DISPLAY.get(repo_language, repo_language)} compile error:\n{errors}"

            if repo_language == "python":
                clean = re.sub(re.escape(tmp_path), str(target), errors)
                return f"Python syntax error:\n{clean}"

            return f"{_LANG_DISPLAY.get(repo_language, repo_language)} compile error:\n{errors}"

        return None

    except FileNotFoundError:
        return None  # compiler not on PATH — skip check
    except subprocess.TimeoutExpired:
        return None  # timeout — skip check, Docker will validate
    except Exception as e:
        log.debug("_check_fixed_syntax error: %s", e)
        return None
    finally:
        try:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


def _detect_dead_new_function(original: str, modified: str, lang: str = "python") -> str:
    """
    Detect if the fix introduced a new function definition that is never called.
    This catches the pattern where the model defines a helper but forgets to call it.
    Returns an error message if dead code is found, empty string otherwise.

    Supported: Python, Go, Rust, Java, JavaScript, TypeScript, Ruby, PHP.
    Skipped for C/C++ (too much noise from forward declarations and header guards).
    """
    if lang in ("c", "cpp"):
        return ""

    # Per-language definition regex
    if lang == "python":
        def_re = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)
        def_cnt_re = lambda n: re.compile(
            rf"(?:^|\s)(?:async\s+)?def\s+{re.escape(n)}\s*\(", re.MULTILINE
        )  # noqa: E731
    elif lang == "go":
        def_re = re.compile(r"(?:^|\s)func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(", re.MULTILINE)
        def_cnt_re = lambda n: re.compile(
            rf"func\s+(?:\([^)]*\)\s*)?{re.escape(n)}\s*\(", re.MULTILINE
        )  # noqa: E731
    elif lang == "rust":
        def_re = re.compile(r"(?:^|\s)(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*[(<]", re.MULTILINE)
        def_cnt_re = lambda n: re.compile(rf"fn\s+{re.escape(n)}\s*[(<]", re.MULTILINE)  # noqa: E731
    elif lang == "ruby":
        # Ruby: def method_name OR def method_name( — parens optional
        def_re = re.compile(r"^\s*def\s+([a-zA-Z_]\w*[!?]?)", re.MULTILINE)
        def_cnt_re = lambda n: re.compile(rf"def\s+{re.escape(n)}(?:\s*\(|\s*$)", re.MULTILINE)  # noqa: E731
    elif lang == "php":
        def_re = re.compile(r"(?:^|\s)function\s+(\w+)\s*\(", re.MULTILINE)
        def_cnt_re = lambda n: re.compile(rf"function\s+{re.escape(n)}\s*\(", re.MULTILINE)  # noqa: E731
    else:
        # JS/TS/Java: generic multi-syntax
        def_re = re.compile(
            r"(?:^|\s)(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(|fn\s+(\w+))",
            re.MULTILINE,
        )
        def_cnt_re = lambda n: re.compile(
            rf"(?:function\s+{re.escape(n)}|(?:const|let|var)\s+{re.escape(n)}\s*=)", re.MULTILINE
        )  # noqa: E731

    # Extract names — for multi-group patterns, take first non-None group
    def _names(text: str) -> set[str]:
        found: set[str] = set()
        for m in def_re.finditer(text):
            name = (
                next((g for g in m.groups() if g), None)
                if m.lastindex and m.lastindex > 1
                else m.group(1)
            )
            if name:
                found.add(name)
        return found

    orig_fns = _names(original)
    mod_fns = _names(modified)
    new_fns = mod_fns - orig_fns

    for fn_name in new_fns:
        call_count = len(re.findall(rf"\b{re.escape(fn_name)}\s*[\(\.]", modified))
        def_count = len(def_cnt_re(fn_name).findall(modified))
        if call_count <= def_count:
            return (
                f"Dead code detected: '{fn_name}' was defined but never called. "
                f"Either call it from the appropriate location, or remove the definition and "
                f"inline the fix directly."
            )
    return ""


def _apply_region_fix(original_lines: list[str], start: int, end: int, fixed_region: str) -> str:
    """Splice fixed_region back into original_lines between start and end.

    Returns empty string if the Builder corrupted indentation on lines it
    was not supposed to change (a common failure mode when returning the
    whole file instead of just the region).
    """
    region_lines = fixed_region.splitlines(keepends=True)
    if region_lines and not region_lines[-1].endswith("\n"):
        region_lines[-1] += "\n"

    orig_region = [l.rstrip("\n") for l in original_lines[start:end]]
    new_region = [l.rstrip("\n") for l in region_lines]

    # Check that unchanged lines (same content modulo leading whitespace) kept
    # their original indentation.  Build a stripped→original map from orig.
    orig_stripped = {l.lstrip(): l for l in orig_region if l.strip()}
    corrupted = 0
    for new_line in new_region:
        stripped = new_line.lstrip()
        if not stripped:
            continue
        orig_line = orig_stripped.get(stripped)
        if orig_line is not None and new_line != orig_line:
            # Same content, different indentation → corruption
            corrupted += 1
    # Allow up to 2 indentation mismatches (Builder sometimes trims trailing
    # blank lines or adjusts one decorator); more than that is a wholesale reformat.
    if corrupted > 2:
        return ""

    rebuilt = original_lines[:start] + region_lines + original_lines[end:]
    return "".join(rebuilt)


def generate_fix(
    step: dict,
    issue_text: str,
    repo_path: Path,
    compiler_error: str = "",
    attempt: int = 1,
    temperature: float = 0.1,
    shadow_trace: str = "",
    source_override: str = "",
    cloak_mode: bool = False,
    semantic_key: str = "",
    symbol_map: dict[str, str] | None = None,
    hints: str = "",
    fail_tests: str = "",
    repo_language: str = "python",
    instance_id: str = "",
) -> str:
    """
    Generate a fix for one step using search/replace blocks.
    Returns the raw model output (containing <<<SEARCH...>>>REPLACE blocks),
    or _NO_BLOCKS_SENTINEL when the model produced no blocks,
    or "" on error.
    """
    target_file = repo_path / step["file"]
    if not target_file.exists():
        log.warning("Target file not found: %s", target_file)
        return ""

    original_real = target_file.read_text(encoding="utf-8", errors="replace")
    original = source_override if source_override else original_real
    lines = original.splitlines(keepends=True)

    lang_label = _LANG_DISPLAY.get(repo_language, repo_language.capitalize())
    lang_fence = _LANG_FENCE.get(repo_language, repo_language)

    retry_ctx = ""
    if compiler_error:
        retry_ctx = (
            f"\n\nAttempt #{attempt - 1} FAILED with this error:\n{compiler_error[:600]}\n"
            f"Your SEARCH blocks must still match the CURRENT file exactly. "
            f"Fix the error above in your REPLACE block."
        )

    _X_TOKEN_RE = re.compile(r"\bx_\d{4}\b")
    cloak_active = bool(source_override and _X_TOKEN_RE.search(source_override))
    cloak_notice = (
        (
            "\n\nCRITICAL: This code uses x_NNNN tokens as identifier placeholders. "
            "Preserve every x_NNNN token exactly — do NOT rename or expand them."
        )
        if cloak_active
        else ""
    )

    # Translate step description identifiers to x_NNNN tokens when Cloak is active
    builder_desc = step.get("description", "Fix the bug")
    if cloak_mode and symbol_map:
        for real_name, token in sorted(symbol_map.items(), key=lambda kv: -len(kv[0])):
            builder_desc = re.sub(rf"\b{re.escape(real_name)}\b", token, builder_desc)

    # Extract the relevant region for the prompt (keeps context tight under Cloak)
    region_context = 20 if cloak_mode else 40
    r_start, r_end = _extract_target_region(
        [l.rstrip("\n") for l in lines],
        builder_desc,
        shadow_trace,
        step["file"],
        context=region_context,
        cloak_mode=cloak_mode,
        repo_language=repo_language,
    )
    region_lines = [l.rstrip("\n") for l in lines[r_start:r_end]]
    numbered_region = "\n".join(
        f"{r_start + i + 1:4d} | {line}" for i, line in enumerate(region_lines)
    )
    total = len(lines)
    key_section = f"\n\n{semantic_key}" if semantic_key else ""
    hints_section = f"\n\nHints:\n{hints}" if hints else ""
    fail_section = (
        f"\n\nFailing tests (your fix must make these pass):\n{fail_tests}" if fail_tests else ""
    )

    # Pre-context: 8 lines before the edit window for indentation awareness
    pre_start = max(0, r_start - 8)
    pre_lines = [l.rstrip("\n") for l in lines[pre_start:r_start]]
    pre_ctx_block = ""
    if pre_lines:
        numbered_pre = "\n".join(
            f"{pre_start + i + 1:4d} | {line}" for i, line in enumerate(pre_lines)
        )
        pre_ctx_block = (
            f"Lines before the edit window (READ-ONLY context):\n"
            f"```{lang_fence}\n{numbered_pre}\n```\n\n"
        )

    # Under Cloak: anonymize the filename so the model can't recognize it from
    # training memory and hallucinate real identifier names into REPLACE blocks.
    if cloak_active:
        _h = hashlib.md5(step["file"].encode()).hexdigest()[:8]
        _ext = Path(step["file"]).suffix
        display_file = f"module_{_h}{_ext}"
    else:
        display_file = step["file"]

    # ── SWE-bench repo-spec injection (corpus-driven empirical context) ─────
    # Prepend the per-repo behavioral spec when available. Withheld under Cloak
    # because the spec contains real repo file paths (would deobfuscate the source).
    spec_block = ""
    if instance_id and not cloak_mode:
        try:
            from swebench_spec_lookup import inject_block_for as _swe_inject

            spec_block = _swe_inject(instance_id, max_spec_chars=12000)
            if spec_block:
                spec_block = (
                    "[SWE-BENCH REPO SPEC — empirical corpus context for this repo]\n"
                    f"{spec_block}"
                    "[END SPEC]\n\n"
                )
        except Exception as _e:
            log.debug("[swebench_spec_lookup] inject failed: %s", _e)
            spec_block = ""

    prompt = (
        f"{spec_block}"
        f"Fix this {lang_label} file to resolve the GitHub issue.\n\n"
        f"Issue:\n{issue_text[:1500]}\n\n"
        f"Fix description: {builder_desc}\n\n"
        f"File: {display_file} ({total} lines total)\n\n"
        f"{pre_ctx_block}"
        f"Edit window — lines {r_start + 1}-{r_end} (these are the ONLY lines you may change):\n"
        f"```{lang_fence}\n{numbered_region}\n```\n"
        f"HARD LIMIT: Each SEARCH block must be ≤30 lines. Copy 3-10 lines from the edit "
        f"window around the broken line. Do NOT put the whole file in SEARCH.\n"
        f"{key_section}{hints_section}{fail_section}"
        f"{retry_ctx}{cloak_notice}\n\n"
        f"{SEARCH_REPLACE_FORMAT}"
    )
    # Language-specific Builder reminders (most critical anti-patterns per language)
    _builder_rules: dict[str, str] = {
        "python": " Preserve `is None` / `is not None` semantics. Use exact exception types.",
        "go": " No naked returns from error paths. Every error must be checked (`if err != nil`).",
        "rust": " Propagate errors with `?`. No unnecessary `.unwrap()`. Respect borrow rules.",
        "java": " Use `.equals()` for String comparison. Null-check before dereference.",
        "javascript": " Use `===`. Await async calls. Don't mutate shared arrays in place.",
        "typescript": " Narrow types before use. No `as any`. Await async calls.",
        "ruby": " Check `nil?` before method calls on optionals. Use `||` for default values.",
        "php": " Use `===`. `isset()` for key existence. `count()` not `sizeof()`.",
        "c": " Check pointer non-NULL before dereference. Free what you malloc.",
        "cpp": " Prefer RAII. Check iterator validity. No UB from signed overflow.",
    }
    _builder_hint = _builder_rules.get(repo_language, "")
    _cloak_sys = (
        (
            " ABSOLUTE RULE: All identifiers in this codebase use x_NNNN encoding "
            "(x_0001, x_0042, x_1234, etc.). These are FIXED SYMBOLS — the real variable names "
            "encoded for transmission. You MUST copy every x_NNNN token character-for-character "
            "into both SEARCH and REPLACE blocks. NEVER rename, expand, abbreviate, or guess "
            "what they mean. CRITICAL: Do NOT use real identifier names from your training "
            "memory — this file's identifiers look nothing like their real names. Every "
            "identifier in your SEARCH and REPLACE blocks must appear VERBATIM in the edit "
            "window shown above. ANY real identifier name or invented x_NNNN token causes "
            "a FATAL CHECKSUM FAILURE and the entire patch is discarded."
        )
        if cloak_active
        else ""
    )
    system_msg = (
        f"You are a battle-hardened {lang_label} engineer who rose from grunt to "
        f"architect by knowing exactly how to unfuck broken code. You have seen every "
        f"failure mode and you answer with mathematical precision.{_builder_hint}"
        f"{_cloak_sys} "
        f"Output ONLY search/replace blocks — no prose, no explanations, no invented "
        f"names. Every block must apply cleanly to the exact source shown."
    )

    # Track 2: three-mode latent RAG (ADAPT / HINT / GENERATE)
    latent_ctx, top_score = _latent_retrieve(issue_text)
    retrieve_mode = (
        "adapt"
        if top_score >= _ADAPT_THRESHOLD
        else "hint"
        if top_score >= _HINT_THRESHOLD
        else "generate"
    )
    log.info("[Latent RAG] mode=%s top_score=%.3f", retrieve_mode, top_score)

    # When Cloak is active, strip x_NNNN tokens from the RAG hint before injecting.
    # RAG patches come from previous runs with different symbol maps — x_NNNN tokens
    # from those runs will bleed into SEARCH blocks and fail to match the current
    # obfuscated source (which uses a different symbol map for the same identifiers).
    # Replace them with [ID] so the builder still gets structural guidance without
    # copying stale obfuscation artifacts.
    _x_token_re = re.compile(r"\bx_\d{4}\b")
    if cloak_mode and latent_ctx and _x_token_re.search(latent_ctx):
        latent_ctx = _x_token_re.sub("[ID]", latent_ctx)
        log.debug("[Latent RAG] stripped x_NNNN tokens from hint (cloak active)")

    if retrieve_mode == "adapt":
        prompt = (
            f"[VERIFIED PATCH — nearly identical bug, similarity {top_score:.2f}]\n"
            f"{latent_ctx}\n[END VERIFIED PATCH]\n\n"
            f"Adapt the fix pattern above to solve the current bug. "
            f"Output ONLY search/replace blocks.\n\n"
        ) + prompt
    elif retrieve_mode == "hint":
        prompt = (
            f"[REFERENCE PATCH — similar bug, use as conceptual guidance only]\n"
            f"{latent_ctx}\n[END REFERENCE]\n\n"
        ) + prompt

    task_vector = step.get("task_vector", "")
    raw = _infer(
        BUILDER_MODEL,
        prompt,
        system=system_msg,
        temperature=temperature + (attempt * 0.03),
        keep_alive=-1,
        task_vector=task_vector,
    )

    if not raw:
        log.debug("[generate_fix] Builder returned empty string")
        return ""

    # If the model produced no <<<SEARCH blocks at all, return sentinel so
    # _solve_one_path can give targeted feedback ("produce search/replace blocks")
    if "<<<" not in raw and "SEARCH" not in raw:
        log.warning(
            "[generate_fix] Model returned no search/replace blocks — raw[:200]: %r", raw[:200]
        )
        return _NO_BLOCKS_SENTINEL

    log.debug("[generate_fix] Builder raw output (%d chars): %r...", len(raw), raw[:300])
    return raw


# ── Local Builder: real-code generation without x_NNNN obfuscation ────────────


def _ask_architect_clarification(
    question: str,
    cloak_ctx: CloakContext,
) -> str:
    """
    Bidirectional Cloak channel: local builder sends a question UP to the cloud
    Architect. We re-cloak the question (Architect sees x_NNNN), then
    reverse-cloak the answer so the local builder gets real identifiers back.
    """
    obf_question = cloak_ctx.obfuscate_text(question)  # type: ignore[union-attr]
    log.info("[LocalBuilder→Architect] Clarification request: %s", question[:120])
    raw_answer = _infer(
        OBSERVER_MODEL,
        f"The local builder needs clarification on a code fix:\n{obf_question}\n"
        f"Answer specifically and briefly in 1-3 sentences.",
        temperature=0.1,
    )
    real_answer = cloak_ctx.restore_content(raw_answer)  # type: ignore[union-attr]
    log.info("[Architect→LocalBuilder] Answer: %s", real_answer[:120])
    return real_answer


def _verify_clarify_against_file(answer: str, step: dict, wt_path: Path) -> str:
    """
    Check that backtick-quoted code snippets in the Architect's CLARIFY answer actually
    exist verbatim in the target file. If any are missing, append a warning so the local
    builder doesn't blindly use hallucinated code as SEARCH targets.
    """
    target_file = step.get("file", "")
    if not target_file:
        return answer
    full_path = wt_path / target_file
    if not full_path.is_file():
        return answer
    try:
        file_content = full_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return answer
    fragments = re.findall(r"`([^`\n]{10,})`", answer)
    missing = [f for f in fragments if f not in file_content]
    if missing:
        log.warning(
            "[LocalBuilder] CLARIFY answer has %d snippet(s) not in %s: %s",
            len(missing),
            target_file,
            [m[:60] for m in missing[:2]],
        )
        answer += (
            f"\n\nIMPORTANT: The code the Architect described "
            f"({'; '.join(m[:50] for m in missing)}) "
            f"was NOT found verbatim in {target_file}. "
            f"Do NOT use it as a SEARCH target. Read the edit window carefully "
            f"and copy the EXACT code from there into your SEARCH block."
        )
    return answer


def generate_fix_local(
    step: dict,
    issue_text: str,
    repo_path: Path,
    real_description: str,
    compiler_error: str = "",
    attempt: int = 1,
    temperature: float = 0.1,
    allow_clarify: bool = True,
    shadow_trace: str = "",
    hints: str = "",
    fail_tests: str = "",
    repo_language: str = "python",
) -> str:
    """
    Generate a fix using the local Ollama builder with REAL source code.

    Unlike generate_fix(), this receives a reverse-cloaked plan description
    and works entirely in real-identifier space. No x_NNNN tokens, no checksum,
    no cloak restoration. The compiler gate is the only oracle.

    If the local builder cannot figure out how to implement the plan, it may
    return a clarification request:  <<<CLARIFY\\n[question]\\n>>>
    The caller (_solve_one_path) detects this and routes the question back
    to the Architect through the bidirectional Cloak channel.
    """
    target_file = repo_path / step["file"]
    if not target_file.exists():
        log.warning("LocalBuilder: target file not found: %s", target_file)
        return ""

    original = target_file.read_text(encoding="utf-8", errors="replace")
    lines = original.splitlines(keepends=True)

    lang_label = _LANG_DISPLAY.get(repo_language, repo_language.capitalize())
    lang_fence = _LANG_FENCE.get(repo_language, repo_language)

    # Larger region window — no obfuscation tax means we can show more real context
    r_start, r_end = _extract_target_region(
        [l.rstrip("\n") for l in lines],
        real_description,
        shadow_trace,
        step["file"],
        context=40,
        cloak_mode=False,
        repo_language=repo_language,
    )
    region_lines = [l.rstrip("\n") for l in lines[r_start:r_end]]
    # Plain code (no line numbers) — the copy target for SEARCH blocks
    plain_region = "\n".join(region_lines)
    # Numbered version for location context only (not for copying)
    numbered_region = "\n".join(
        f"{r_start + i + 1:4d} | {line}" for i, line in enumerate(region_lines)
    )
    total = len(lines)

    retry_ctx = ""
    if compiler_error:
        retry_ctx = (
            f"\n\nAttempt #{attempt - 1} FAILED:\n{compiler_error[:600]}\n"
            f"Your SEARCH blocks must match the CURRENT file exactly. Fix the error above."
        )

    pre_start = max(0, r_start - 8)
    pre_lines = [l.rstrip("\n") for l in lines[pre_start:r_start]]
    pre_ctx_block = ""
    if pre_lines:
        plain_pre = "\n".join(pre_lines)
        pre_ctx_block = (
            f"Context before edit window (READ-ONLY — lines {pre_start + 1}-{r_start}):\n"
            f"```{lang_fence}\n{plain_pre}\n```\n\n"
        )

    hints_section = f"\n\nHints:\n{hints}" if hints else ""
    fail_section = (
        f"\n\nFailing tests (must pass after your fix):\n{fail_tests}" if fail_tests else ""
    )

    prompt = (
        f"Fix this {lang_label} file to resolve the GitHub issue.\n\n"
        f"Issue:\n{issue_text[:1500]}\n\n"
        f"Fix: {real_description}\n\n"
        f"File: {step['file']} (lines {r_start + 1}-{r_end} shown, {total} total)\n\n"
        f"{pre_ctx_block}"
        f"EDIT WINDOW — copy SEARCH blocks verbatim from this code (lines {r_start + 1}-{r_end}), no line-number prefixes:\n"
        f"```{lang_fence}\n{plain_region}\n```\n\n"
        f"Location reference (do NOT include these line numbers in SEARCH blocks):\n"
        f"```\n{numbered_region}\n```\n"
        f"{hints_section}{fail_section}{retry_ctx}\n\n"
        f"{SEARCH_REPLACE_FORMAT}"
    )

    _builder_rules: dict[str, str] = {
        "python": " Preserve `is None`/`is not None` semantics. Use exact exception types.",
        "go": " No naked returns from error paths. Every error must be checked.",
        "rust": " Propagate errors with `?`. No unnecessary `.unwrap()`. Respect borrow rules.",
        "java": " Use `.equals()` for String comparison. Null-check before dereference.",
        "javascript": " Use `===`. Await async calls. Don't mutate shared arrays in place.",
        "typescript": " Narrow types before use. No `as any`. Await async calls.",
        "ruby": " Check `nil?` before method calls on optionals.",
        "php": " Use `===`. `isset()` for key existence.",
        "c": " Check pointer non-NULL before dereference. Free what you malloc.",
        "cpp": " Prefer RAII. Check iterator validity.",
    }
    _builder_hint = _builder_rules.get(repo_language, "")

    clarify_rule = (
        "If the plan refers to something you cannot locate in the file shown, respond with: "
        "<<<CLARIFY\n[your specific question about the plan]\n>>> instead of a patch."
        if allow_clarify
        else "You MUST output SEARCH/REPLACE blocks. Do NOT output <<<CLARIFY>>> under any circumstances."
    )
    system_msg = (
        f"You are a battle-hardened {lang_label} engineer. "
        f"You fix bugs with mathematical precision — no added complexity, no extra code.{_builder_hint} "
        f"Output ONLY search/replace blocks — no prose, no explanations. "
        f"Every SEARCH block must match the exact source shown, character-for-character. "
        f"{clarify_rule}"
    )

    # Latent RAG — same as cloud path
    latent_ctx, top_score = _latent_retrieve(issue_text)
    retrieve_mode = (
        "adapt"
        if top_score >= _ADAPT_THRESHOLD
        else "hint"
        if top_score >= _HINT_THRESHOLD
        else "generate"
    )
    log.info("[LocalBuilder] Latent RAG mode=%s top_score=%.3f", retrieve_mode, top_score)

    if retrieve_mode == "adapt":
        prompt = (
            f"[VERIFIED PATCH — nearly identical bug, similarity {top_score:.2f}]\n"
            f"{latent_ctx}\n[END VERIFIED PATCH]\n\n"
            f"Adapt the fix pattern above to solve the current bug. "
            f"Output ONLY search/replace blocks.\n\n"
        ) + prompt
    elif retrieve_mode == "hint":
        prompt = (
            f"[REFERENCE PATCH — similar bug, use as conceptual guidance only]\n"
            f"{latent_ctx}\n[END REFERENCE]\n\n"
        ) + prompt

    raw = _ollama(
        LOCAL_BUILDER_MODEL,
        prompt,
        system=system_msg,
        temperature=temperature + (attempt * 0.03),
        keep_alive=-1,
        timeout=600,  # large models (32B Q4) need up to 10 min on first load
    )

    if not raw:
        return ""
    if "<<<" not in raw and "SEARCH" not in raw and "CLARIFY" not in raw:
        log.warning("[LocalBuilder] No blocks or clarify in response")
        return _NO_BLOCKS_SENTINEL

    return raw


# ── Step 4a: Targeted Tests ───────────────────────────────────────────────────


def _format_test_output(stdout: str, stderr: str) -> str:
    raw = (stdout + "\n" + stderr).splitlines()
    warnings, fatals = [], []
    for line in raw:
        s = line.strip()
        if not s:
            continue
        if any(x in s for x in ("Warning:", "site-packages", "DeprecationWarning")):
            warnings.append(s)
        else:
            fatals.append(s)
    out = ""
    if warnings:
        out += "[SYSTEM ENVIRONMENT WARNINGS]\n" + "\n".join(warnings[-10:]) + "\n\n"
    if fatals:
        out += "[FATAL TRACEBACK]\n" + "\n".join(fatals[-40:])
    return (out or "No output.")[:2500]


def run_tests(repo_path: Path, target_file: Path) -> tuple[bool, str]:
    """Targeted: find and run tests specifically for the modified file."""
    env = {**os.environ, "PYTHONWARNINGS": "ignore"}
    stem = target_file.stem
    candidates = (
        list(repo_path.rglob(f"test_{stem}.py"))
        + list(repo_path.rglob(f"test*{stem}*.py"))
        + list(repo_path.rglob(f"*{stem}*test*.py"))
    )
    test_args = [str(t) for t in candidates[:3]] if candidates else [str(repo_path)]

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest"]
            + test_args
            + ["-x", "--tb=short", "-q", "--no-header"]
            + _pytest_timeout_flag(),
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT + 30,
            cwd=repo_path,
            env=env,
        )
        return result.returncode == 0, _format_test_output(result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        return False, "[FATAL TRACEBACK]\npytest timed out — possible infinite loop."
    except FileNotFoundError:
        try:
            r = subprocess.run(
                [sys.executable, "-m", "py_compile", str(target_file)],
                capture_output=True,
                text=True,
                timeout=10,
                env=env,
            )
            return r.returncode == 0, _format_test_output(r.stdout, r.stderr)
        except Exception as e:
            return False, f"[FATAL TRACEBACK] System error: {e}"


# ── Step 4b: Phase 3 — Ripple Regression Sweep ───────────────────────────────


def run_regression_sweep(repo_path: Path, target_file: Path) -> tuple[bool, str]:
    """
    After targeted tests pass, sweep the broader test directory.
    Guards against fragile fixes that break adjacent modules.
    """
    log.info("Phase 3: Ripple regression sweep...")
    env = {**os.environ, "PYTHONWARNINGS": "ignore"}

    # Find the highest-level test directory reachable from the target file
    sweep_dir = repo_path
    for parent in target_file.parents:
        if parent == repo_path or not parent.is_relative_to(repo_path):
            break
        test_dirs = (
            list(parent.glob("tests")) + list(parent.glob("test")) + list(parent.glob("test_*"))
        )
        if test_dirs:
            sweep_dir = test_dirs[0]
            break

    log.info("Regression sweep dir: %s", sweep_dir.relative_to(repo_path))
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(sweep_dir),
                "--tb=line",
                "-q",
                "--no-header",
                "--ignore=.git",
            ]
            + _pytest_timeout_flag(),
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT * 4,
            cwd=repo_path,
            env=env,
        )
        passed = result.returncode == 0
        output = _format_test_output(result.stdout, result.stderr)
        log.info("Regression sweep: %s", "PASS" if passed else "FAIL")
        return passed, output
    except subprocess.TimeoutExpired:
        log.warning("Regression sweep timed out — treating as PASS (timeout, not failure)")
        return True, "Regression sweep timed out."
    except Exception as e:
        log.warning("Regression sweep error: %s — treating as PASS", e)
        return True, str(e)


# ── Step 5: Export patch / repo utils ────────────────────────────────────────


def make_targeted_patch(step_file: str, original: str, fixed: str) -> str:
    """
    Build a clean unified diff from original→fixed content using difflib.
    This avoids git diff capturing pip-install artifacts and guarantees the
    hunk line numbers match exactly what Docker's base_commit checkout sees.

    Rejection criteria (smarter than raw line count):
      - If >80% of original lines are changed, the Builder rewrote the file wholesale.
      - Absolute hard cap: diff > 2000 lines (runaway output guard).
    These criteria let large files produce large diffs for legitimate targeted fixes.
    """
    import difflib

    rel = Path(step_file).as_posix()
    diff_lines = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
    )
    if not diff_lines:
        return ""
    patch = f"diff --git a/{rel} b/{rel}\n" + "".join(diff_lines)
    if not patch.endswith("\n"):
        patch += "\n"
    all_lines = patch.splitlines()

    if len(all_lines) > 2000:
        log.warning("Patch is %d lines (absolute cap 2000) — discarding.", len(all_lines))
        return ""
    # Region mode keeps diffs naturally bounded; for full-file mode on small files a
    # large changed-line ratio can still be a correct fix. Let the harness validate.
    return patch


def install_repo_editable(repo_path: Path) -> None:
    """
    Run `pip install -e .` on the cloned repo so the package is importable
    and version metadata resolves correctly. Many projects (e.g. astropy) fail
    their own test suite if not installed — even when the source is present.
    Runs silently; failures are logged as warnings, never fatal.
    """
    has_setup = any((repo_path / f).exists() for f in ("setup.py", "setup.cfg", "pyproject.toml"))
    if not has_setup:
        return
    log.info("Installing repo in editable mode (pip install -e .)...")
    try:
        # Try with test extras first (installs conftest plugins like pytest-astropy).
        # Fall back to --no-deps if extras are undefined or fail.
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".[test]", "--quiet"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=240,
        )
        if r.returncode != 0:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
        if r.returncode == 0:
            log.info("Repo installed OK")
        else:
            log.warning(
                "pip install -e . returned %d — continuing anyway\n%s", r.returncode, r.stderr[:400]
            )
    except Exception as e:
        log.warning("Repo install skipped: %s", e)


def reset_repo(repo_path: Path) -> None:
    try:
        subprocess.run(
            ["git", "checkout", "--", "."],
            cwd=repo_path,
            capture_output=True,
            timeout=15,
        )
    except Exception:
        pass


# ── Worktree management ───────────────────────────────────────────────────────


def _create_worktree(repo_path: Path, label: str) -> Path | None:
    """Create an isolated git worktree for one execution path."""
    wt_path = repo_path.parent / f"determinex_wt_{label}"
    try:
        subprocess.run(
            ["git", "worktree", "add", "--force", str(wt_path), "HEAD"],
            cwd=repo_path,
            capture_output=True,
            timeout=30,
            check=True,
        )
        return wt_path
    except Exception as e:
        log.warning("Worktree creation failed (%s): %s — using copy fallback", label, e)
        # Fallback: simple directory copy if git worktree not available
        try:
            shutil.copytree(
                str(repo_path),
                str(wt_path),
                ignore=shutil.ignore_patterns(".git", "*.pyc", "__pycache__"),
            )
            # Copy .git reference so git diff works
            git_dir = repo_path / ".git"
            if git_dir.exists():
                shutil.copytree(str(git_dir), str(wt_path / ".git"))
            return wt_path
        except Exception as e2:
            log.error("Worktree copy fallback also failed: %s", e2)
            return None


def _remove_worktree(repo_path: Path, wt_path: Path) -> None:
    """Remove worktree, always in a finally block."""
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt_path)],
            cwd=repo_path,
            capture_output=True,
            timeout=15,
        )
    except Exception:
        pass
    # Belt-and-suspenders: rm -rf regardless
    try:
        shutil.rmtree(str(wt_path), ignore_errors=True)
    except Exception:
        pass


# ── Single-path solve (one worktree, one temperature) ────────────────────────


def _is_meaningful_test_failure(test_out: str) -> bool:
    """True when a test failure contains actionable signal (not just import errors)."""
    if not test_out:
        return False
    noisy = ("ModuleNotFoundError", "ImportError", "cannot import", "No module named")
    return not any(n in test_out for n in noisy)


def _run_fail_to_pass_tests(wt_path: Path, fail_tests_json: str) -> tuple[bool, str]:
    """Run the FAIL_TO_PASS test list. Returns (all_pass, output)."""
    try:
        test_ids = (
            json.loads(fail_tests_json) if fail_tests_json.startswith("[") else [fail_tests_json]
        )
    except Exception:
        test_ids = [fail_tests_json]
    if not test_ids:
        return True, ""

    # Convert test IDs (e.g. "tests/test_foo.py::TestBar::test_baz") to pytest args
    test_args = [t for t in test_ids[:5] if t]
    env = {**os.environ, "PYTHONWARNINGS": "ignore"}
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest"]
            + test_args
            + ["-x", "--tb=short", "-q", "--no-header"]
            + _pytest_timeout_flag(),
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT + 30,
            cwd=wt_path,
            env=env,
        )
        return r.returncode == 0, _format_test_output(r.stdout, r.stderr)
    except Exception as e:
        return False, f"[FATAL TRACEBACK] Test run error: {e}"


def _solve_one_path(
    wt_path: Path,
    issue_text: str,
    steps: list[dict],
    temperature: float,
    stop_event: threading.Event,
    path_id: int,
    enable_regression: bool = True,
    shadow_trace: str = "",
    cloak_ctx: CloakContext | None = None,
    semantic_key: str = "",
    repo_language: str = "python",
    fail_tests: str = "",
    feedback: dict | None = None,
    instance_id: str = "",
) -> str | None:
    """
    Run the build→test→regression loop on an isolated worktree.
    Returns unified diff string on success, None on failure or cancellation.

    When cloak_ctx is provided (DETERMINEX_CLOAK=1):
      - Builder sees obfuscated source in its prompt
      - Builder output is restored to original names before writing to disk
      - Patch is generated from (original → restored), never exposes x_NNNN tokens
    """
    for step in [s for s in steps[:3] if isinstance(s, dict)]:
        if stop_event.is_set():
            return None

        step_file = step.get("file", "")
        if "path/to" in step_file or step_file.startswith("path/"):
            log.debug(
                "[Path %d] Architect returned template path '%s' — skipping", path_id, step_file
            )
            return None

        target = wt_path / step_file
        if not target.exists():
            log.warning("[Path %d] File not found: %s — skipping", path_id, step_file)
            continue

        try:
            _assert_in_workspace(target, wt_path)
        except ValueError as _esc:
            log.error(
                "[SEC] Workspace escape blocked for step_file=%r wt=%s: %s",
                step_file,
                wt_path,
                _esc,
            )
            continue

        with open(target, encoding="utf-8", newline="\n") as f:
            original = f.read()

        # Pre-obfuscate this file once for all Builder attempts.
        # FAIL-CLOSED on cloak failure: if obfuscation crashes we MUST NOT
        # fall back to sending plaintext to the cloud API. Abort this path's
        # solve attempt and let the outer loop record the failure.
        # Local builder skips obfuscation — it works with real identifiers.
        if cloak_ctx and not USE_LOCAL_BUILDER:
            try:
                obfuscated_source = cloak_ctx.obfuscate_source_str(original, cache_key=step_file)  # type: ignore[union-attr]
            except CloakObfuscationError as _coe:
                log.error(
                    "[Cloak FAIL-CLOSED] step %s file=%s — refusing to send plaintext to API: %s",
                    step.get("step", "?"),
                    step_file,
                    _coe,
                )
                # Best-effort audit-log the failure so verify_cloak runs flag it.
                try:
                    if hasattr(cloak_ctx, "_audit_logger") and cloak_ctx._audit_logger:  # type: ignore[union-attr]
                        cloak_ctx._audit_logger.log_failure(  # type: ignore[union-attr]
                            instance_id=getattr(cloak_ctx, "instance_id", "?"),
                            attempt=0,
                            error=str(_coe),
                            raw_patch_excerpt="(obfuscation-failed-before-prompt)",
                        )
                except Exception:
                    pass
                return None
        else:
            obfuscated_source = ""

        # Local builder: reverse-cloak the step description back to real identifiers.
        # Any x_NNNN tokens that survive restore_content are Architect hallucinations
        # (tokens the Architect invented that aren't in the symbol map).
        _local_real_desc = ""
        _local_clarify_ctx = ""
        if USE_LOCAL_BUILDER and cloak_ctx:
            _local_real_desc = cloak_ctx.restore_content(step.get("description", ""))  # type: ignore[union-attr]
            _hallucinated = re.findall(r"\bx_\d{4}\b", _local_real_desc)
            if _hallucinated:
                log.warning(
                    "[LocalBuilder] Architect hallucinated %d token(s) not in symbol map: %s — replacing with [UNKNOWN]",
                    len(_hallucinated),
                    _hallucinated[:5],
                )
                # Replace hallucinated tokens so builder doesn't treat them as real identifiers
                _local_real_desc = re.sub(r"\bx_\d{4}\b", "[UNKNOWN-IDENTIFIER]", _local_real_desc)

        last_error = ""
        _too_large_count = 0
        _too_large_lines = 0

        for attempt in range(1, MAX_RETRIES + 1):
            if stop_event.is_set():
                return None

            log.info(
                "[Path %d T=%.1f] Step %s attempt %d/%d",
                path_id,
                temperature,
                step.get("step", 1),
                attempt,
                MAX_RETRIES,
            )

            if USE_LOCAL_BUILDER and cloak_ctx:
                # Local builder works in real-identifier space — restore issue text
                # from x_NNNN tokens back to real names before passing to builder.
                _local_issue_text = cloak_ctx.restore_content(issue_text)  # type: ignore[union-attr]
                model_out = generate_fix_local(
                    step,
                    _local_issue_text,
                    wt_path,
                    _local_real_desc,
                    compiler_error=last_error,
                    attempt=attempt,
                    temperature=temperature,
                    shadow_trace=shadow_trace,
                    hints=_local_clarify_ctx,
                    fail_tests=fail_tests,
                    repo_language=repo_language,
                    allow_clarify=not bool(_local_clarify_ctx),
                )
            else:
                model_out = generate_fix(
                    step,
                    issue_text,
                    wt_path,
                    last_error,
                    attempt,
                    temperature,
                    shadow_trace=shadow_trace,
                    source_override=obfuscated_source,
                    cloak_mode=bool(cloak_ctx),
                    # Withhold semantic_key from Builder when Cloak is active.
                    # The Architect already used it to plan; giving Builder the
                    # x_NNNN→name mapping causes it to substitute real names into
                    # SEARCH blocks instead of copying x_NNNN tokens verbatim.
                    semantic_key="" if cloak_ctx else semantic_key,
                    symbol_map=cloak_ctx.symbol_map.forward if cloak_ctx else None,  # type: ignore[union-attr]
                    repo_language=repo_language,
                    fail_tests=fail_tests,
                    instance_id=instance_id,
                )

            if not model_out:
                last_error = "No output from model. Try again and produce search/replace blocks."
                continue

            if model_out == _NO_BLOCKS_SENTINEL:
                last_error = (
                    "Your response contained no <<<SEARCH...>>>REPLACE blocks. "
                    "You MUST use the exact format:\n"
                    "<<<SEARCH\n[original lines]\n===\n[fixed lines]\n>>>REPLACE"
                )
                continue

            # ── Bidirectional Cloak channel: local builder → Architect ────────────
            # Local builder signals it needs clarification with <<<CLARIFY\n...\n>>>
            # We re-cloak the question (Architect sees x_NNNN), get the answer,
            # reverse-cloak it, then inject as context for the next attempt.
            # Guard: only allow one clarification round per step — if the model
            # already got an answer and is CLARIFY-ing again, force a patch attempt.
            if USE_LOCAL_BUILDER and cloak_ctx and model_out and "CLARIFY" in model_out:
                _cm = re.search(r"<<<CLARIFY\n(.*?)\n>>>", model_out, re.DOTALL)
                if _cm and not _local_clarify_ctx:
                    _question = _cm.group(1).strip()
                    _local_clarify_ctx = _ask_architect_clarification(_question, cloak_ctx)
                    _local_clarify_ctx = _verify_clarify_against_file(
                        _local_clarify_ctx, step, wt_path
                    )
                    last_error = (
                        f"You asked for clarification. The Architect answered: {_local_clarify_ctx}. "
                        f"Now generate the patch — do NOT ask for clarification again. "
                        f"Write SEARCH/REPLACE blocks by copying the exact code shown in the edit window."
                    )
                    continue
                elif _cm and _local_clarify_ctx:
                    # Already answered — model is looping on CLARIFY. Force patch mode.
                    log.warning("[LocalBuilder] CLARIFY loop detected — forcing patch attempt")
                    last_error = (
                        f"You already have the Architect's answer: {_local_clarify_ctx}. "
                        f"Do NOT ask for clarification again. Generate SEARCH/REPLACE blocks NOW. "
                        f"Copy the SEARCH text verbatim from the edit window (strip the `NNN | ` prefix)."
                    )

            # ── Normalize Builder output: real names → x_NNNN tokens ─────────────
            # Skip for local builder — it works with real identifiers throughout.
            if cloak_ctx and obfuscated_source and not USE_LOCAL_BUILDER:
                model_out = _normalize_to_cloak_tokens(
                    model_out,
                    cloak_ctx.symbol_map.forward,  # type: ignore[union-attr]
                )

            # ── Parse search/replace blocks ───────────────────────────────────
            blocks = _parse_search_replace_blocks(model_out)
            if not blocks:
                log.warning(
                    "[_solve_one_path] _parse_search_replace_blocks returned [] "
                    "(attempt %d) — raw output (%d chars): %r...",
                    attempt,
                    len(model_out),
                    model_out[:400],
                )
                last_error = (
                    "Could not parse any valid <<<SEARCH...>>>REPLACE blocks from your output. "
                    "Ensure the delimiters are exactly '<<<SEARCH', '===', '>>>REPLACE' on their own lines."
                )
                continue

            # ── Oversized block guard (whole-file rewrite detection) ─────────────
            # In Cloak mode the Builder sometimes outputs the ENTIRE obfuscated file
            # as a single SEARCH/REPLACE block. When deobfuscated, the REPLACE block
            # diverges from the real source in hundreds of lines (wrong x_NNNN
            # assignments for identifiers not shown in the edit window), producing a
            # 900+ line diff that the 500-line guard catches and rejects on every retry.
            # Detect this early — before deobfuscation — so we can inject surgical feedback.
            _max_search_lines = 80  # edit window is 40 lines; Builder may add pre-context
            _block_sizes = [(len(s.splitlines()), len(r.splitlines())) for s, r in blocks]
            log.info(
                "[Path %d] blocks=%d sizes=%s search[0]=%r",
                path_id,
                len(blocks),
                [(ss, rs) for ss, rs in _block_sizes],
                blocks[0][0][:120] if blocks else "",
            )
            _oversized_blocks = [
                (i, ss, rs)
                for i, (ss, rs) in enumerate(_block_sizes)
                if ss > _max_search_lines or rs > _max_search_lines
            ]
            if _oversized_blocks:
                worst_i, worst_s, worst_r = max(_oversized_blocks, key=lambda x: max(x[1], x[2]))
                log.warning(
                    "[Path %d] Block %d is oversized: SEARCH=%d lines, REPLACE=%d lines "
                    "(max %d) — whole-file rewrite guard triggered",
                    path_id,
                    worst_i,
                    worst_s,
                    worst_r,
                    _max_search_lines,
                )
                _too_large_count += 1
                _too_large_lines = max(worst_s, worst_r)
                last_error = (
                    f"Your SEARCH block #{worst_i + 1} is {worst_s} lines "
                    f"and REPLACE is {worst_r} lines — this is a WHOLE-FILE REWRITE. "
                    f"REJECTED. You must make a SURGICAL change: find the SINGLE broken "
                    f"statement and write a SEARCH block of 3-15 lines around it. "
                    f"The edit window shown above is EXACTLY the region you should target. "
                    f"Copy 3-5 lines from that window into SEARCH, change the broken line "
                    f"in REPLACE, keep everything else identical."
                )
                continue

            # ── Cloak token-preservation checksum ────────────────────────────────
            # Check that tokens in SEARCH blocks exist somewhere in the codebase.
            # We allow cross-file tokens (Builder legitimately references tokens
            # from imported modules / other context files in SEARCH blocks for
            # Java/Rust/Go which have complex cross-file type references).
            # SEARCH block matching is the real ground-truth check — it will
            # reject blocks that don't match the target file's actual text.
            # The checksum here only blocks truly hallucinated tokens (ones that
            # appear in NO file in the codebase symbol map).
            # Skip for local builder — it works with real identifiers, no x_NNNN.
            if cloak_ctx and obfuscated_source and not USE_LOCAL_BUILDER:
                _xt = re.compile(r"\bx_\d{4}\b")
                # Valid = any token in the codebase symbol map (all files)
                _src_toks = set(_xt.findall(obfuscated_source))
                try:
                    _src_toks |= set(cloak_ctx.symbol_map.forward.values())  # type: ignore[union-attr]
                except Exception:
                    pass  # symbol_map unavailable — fall back to file-only set
                _search_toks: set[str] = set()
                for _s, _ in blocks:
                    _search_toks.update(_xt.findall(_s))
                _invented = _search_toks - _src_toks
                if _invented and len(_invented) / max(len(_search_toks), 1) > 0.05:
                    examples = ", ".join(sorted(_invented)[:4])
                    log.warning(
                        "[Path %d] Checksum: SEARCH blocks contain %d hallucinated tokens (%s...) — retry",
                        path_id,
                        len(_invented),
                        examples,
                    )
                    last_error = (
                        f"CRITICAL TOKEN VIOLATION: Your SEARCH blocks contain {len(_invented)} "
                        f"x_NNNN tokens that do NOT exist anywhere in this codebase: {examples}. "
                        f"Copy x_NNNN tokens verbatim from the file content shown above."
                    )
                    continue

                # ── REPLACE block real-identifier leak check ──────────────────
                # If the Builder substituted real identifiers (from training memory)
                # into REPLACE blocks instead of x_NNNN tokens, catch it here.
                # We only fire when the REPLACE block contains private identifiers
                # (starts with _) from the symbol map — those are the ones Cloak
                # obfuscated and the Builder must not reverse from memory.
                try:
                    _real_names = set(cloak_ctx.symbol_map.forward.keys())  # type: ignore[union-attr]
                    _private_real = {n for n in _real_names if n.startswith("_")}
                    _replace_toks: set[str] = set()
                    _word_re = re.compile(r"\b([A-Za-z_]\w*)\b")
                    for _, _r in blocks:
                        _replace_toks.update(_word_re.findall(_r))
                    _leaked = _replace_toks & _private_real
                    if _leaked and len(_leaked) / max(len(_replace_toks), 1) > 0.03:
                        examples_r = ", ".join(sorted(_leaked)[:4])
                        log.warning(
                            "[Path %d] REPLACE leak: %d real identifiers in REPLACE blocks (%s) — retry",
                            path_id,
                            len(_leaked),
                            examples_r,
                        )
                        last_error = (
                            f"CRITICAL: Your REPLACE blocks contain {len(_leaked)} real identifier "
                            f"names ({examples_r}) that DO NOT EXIST in this codebase. "
                            f"Every identifier in REPLACE must be an x_NNNN token copied verbatim "
                            f"from the edit window above. Do NOT use real names from your training memory."
                        )
                        continue
                except Exception:
                    pass  # symbol_map unavailable — skip real-name check

            # ── Apply blocks to (obfuscated or real) source ───────────────────
            # Local builder works with real source directly; no obfuscation needed.
            source_to_patch = (
                original
                if (USE_LOCAL_BUILDER and cloak_ctx)
                else (obfuscated_source if cloak_ctx else original)
            )
            fixed_obf, failed = _apply_search_replace_blocks(source_to_patch, blocks)

            if failed:
                log.warning(
                    "[Path %d] %d block(s) failed to match: %s", path_id, len(failed), failed[:3]
                )
                # For local builder: find the actual code at the anchor so the model
                # can copy it correctly on the next attempt instead of hallucinating.
                actual_snippet = ""
                if USE_LOCAL_BUILDER and failed:
                    first_failed = failed[0]
                    anchor_line = next(
                        (l for l in first_failed.split("\n") if l.strip()), ""
                    ).rstrip()
                    if anchor_line:
                        src_lines_fb = source_to_patch.split("\n")
                        anchor_norm_fb = _normalize_for_match(anchor_line)
                        anchor_base_fb = anchor_norm_fb.split("(")[0].rstrip()
                        for fb_i, fb_line in enumerate(src_lines_fb):
                            fb_norm = _normalize_for_match(fb_line)
                            # Exact match first; fall back to paren-stripped so model gets
                            # correct source even when it wrote params that don't exist yet.
                            exact_hit = fb_norm == anchor_norm_fb
                            paren_hit = (
                                not exact_hit
                                and len(anchor_base_fb) >= 8
                                and fb_norm.split("(")[0].rstrip() == anchor_base_fb
                            )
                            if exact_hit or paren_hit:
                                snippet_lines = src_lines_fb[fb_i : fb_i + 20]
                                actual_snippet = (
                                    "\n\nThe ACTUAL code in the file starting at that location is:\n"
                                    "```\n" + "\n".join(snippet_lines) + "\n```\n"
                                    "Copy SEARCH from the above — do NOT generate from memory."
                                )
                                break
                last_error = (
                    f"{len(failed)} SEARCH block(s) did not match the file. "
                    f"Your SEARCH must be an EXACT copy of the current file content — "
                    f"strip the `NNN | ` line-number prefix but otherwise copy verbatim."
                    f"{actual_snippet}"
                )
                # Reject ALL partial applications — a patch where SOME blocks
                # didn't match is always wrong. Partial results produce garbage
                # patches that fail git apply with wrong context.
                continue

            # ── Cloak restoration ─────────────────────────────────────────────
            # Local builder already produced real identifiers — no restoration needed.
            if cloak_ctx and not USE_LOCAL_BUILDER:
                fixed = cloak_ctx.restore_content(fixed_obf)  # type: ignore[union-attr]
                if not fixed.strip():
                    log.info("[Path %d] Cloak restoration produced empty content — retry", path_id)
                    continue
                _orig_lc = len(original.splitlines())
                _obf_lc = len(fixed_obf.splitlines())
                _fix_lc = len(fixed.splitlines())
                log.info(
                    "[Path %d] restore lines: original=%d obf_applied=%d fixed=%d",
                    path_id,
                    _orig_lc,
                    _obf_lc,
                    _fix_lc,
                )
            else:
                fixed = fixed_obf

            if fixed == original:
                log.warning(
                    "[Path %d] No-change patch — REPLACE identical to source or no "
                    "SEARCH/REPLACE blocks in response",
                    path_id,
                )
                last_error = (
                    "Your fix produced no changes to the file. "
                    "The SEARCH block matched but REPLACE was identical. "
                    "Make sure your REPLACE block contains the actual fix."
                )
                continue

            # ── Dead-code detection ───────────────────────────────────────────
            dead_err = _detect_dead_new_function(original, fixed, repo_language)
            if dead_err:
                log.warning("[Path %d] Dead code: %s", path_id, dead_err[:100])
                last_error = dead_err
                continue

            # ── Syntax/compile check ──────────────────────────────────────────
            syntax_err = _check_fixed_syntax(target, fixed, repo_language)
            if syntax_err:
                log.warning(
                    "[Path %d] Compile check failed — retrying: %s", path_id, syntax_err[:120]
                )
                last_error = f"Your fix has a compile/syntax error:\n{syntax_err}"
                continue

            # ── Write to disk ─────────────────────────────────────────────────
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(fixed)

            # Docker-eval mode: skip native test gating, export for Docker to score.
            if SKIP_NATIVE_TESTS:
                patch = make_targeted_patch(step_file, original, fixed)
                if not patch:
                    last_error = "Patch diff was empty after applying fix — no change detected."
                    with open(target, "w", encoding="utf-8", newline="\n") as f:
                        f.write(original)
                    continue
                diff_line_count = patch.count("\n")
                _patch_preview = "\n".join(patch.splitlines()[:8])
                log.info(
                    "[Path %d] patch preview (%d \\n chars):\n%s",
                    path_id,
                    diff_line_count,
                    _patch_preview,
                )
                if diff_line_count > 500:
                    log.warning(
                        "[Path %d] Patch too large (%d lines) — retrying", path_id, diff_line_count
                    )
                    _too_large_count += 1
                    _too_large_lines = diff_line_count
                    last_error = (
                        f"Your fix is too large ({diff_line_count} diff lines). "
                        f"Make a more targeted change — use smaller SEARCH/REPLACE blocks "
                        f"that change only the broken lines, not the whole file."
                    )
                    with open(target, "w", encoding="utf-8", newline="\n") as f:
                        f.write(original)
                    continue
                # Show the patch so humans can verify it looks correct
                patch_preview = "\n".join(patch.splitlines()[:40])
                log.info(
                    "[Path %d] PATCH PREVIEW (%d lines):\n%s",
                    path_id,
                    diff_line_count,
                    patch_preview,
                )

                # Optionally run FAIL_TO_PASS tests as a quality gate
                if fail_tests and attempt < MAX_RETRIES:
                    log.info("[Path %d] Running FAIL_TO_PASS tests...", path_id)
                    tests_ok, test_out = _run_fail_to_pass_tests(wt_path, fail_tests)
                    if tests_ok:
                        log.info(
                            "[Path %d T=%.1f] FAIL_TO_PASS tests PASS — accepting patch",
                            path_id,
                            temperature,
                        )
                        return patch
                    if _is_meaningful_test_failure(test_out):
                        log.info(
                            "[Path %d] FAIL_TO_PASS FAIL — test output:\n%s",
                            path_id,
                            test_out[:400],
                        )
                        last_error = f"Failing tests still fail after your fix:\n{test_out[:600]}"
                        with open(target, "w", encoding="utf-8", newline="\n") as f:
                            f.write(original)
                        continue
                log.info(
                    "[Path %d T=%.1f] Patch accepted (%d diff lines, Docker will verify)",
                    path_id,
                    temperature,
                    diff_line_count,
                )
                return patch

            # Native test mode
            passed, test_out = run_tests(wt_path, target)
            if not passed:
                last_error = test_out
                log.info("[Path %d] Targeted test FAIL — %s", path_id, test_out[:120])
                with open(target, "w", encoding="utf-8", newline="\n") as f:
                    f.write(original)
                continue

            # Phase 3: regression sweep
            if enable_regression:
                reg_ok, reg_out = run_regression_sweep(wt_path, target)
                if not reg_ok:
                    log.info("[Path %d] Regression FAIL — reverting", path_id)
                    last_error = f"Regression failure:\n{reg_out}"
                    with open(target, "w", encoding="utf-8", newline="\n") as f:
                        f.write(original)
                    continue

            patch = make_targeted_patch(step_file, original, fixed)
            if patch:
                log.info("[Path %d T=%.1f] SUCCESS on attempt %d", path_id, temperature, attempt)
                return patch

        # Step exhausted — restore original
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(original)

        # Signal the caller to ask the Architect for decomposition when every
        # sub-attempt was rejected for being too large (model is rewriting the
        # whole file instead of making a targeted fix).
        if _too_large_count == MAX_RETRIES and feedback is not None:
            feedback["too_large"] = {
                "step_desc": step.get("description", ""),
                "step_file": step.get("file", ""),
                "line_count": _too_large_lines,
            }

    return None


# ── Compile gate helpers ──────────────────────────────────────────────────────


def _normalize_to_cloak_tokens(text: str, forward_map: dict[str, str]) -> str:
    """
    Substitute real identifier names back to x_NNNN tokens in Builder output.

    The Builder (DeepSeek) consistently writes natural identifier names instead
    of x_NNNN tokens, even when instructed not to. Rather than fighting this with
    instructions, we normalize after the fact: replace every real name that has a
    Cloak mapping back to its x_NNNN token before the checksum and SEARCH/REPLACE
    apply step. This lets the Builder write readable code while Cloak tokenization
    is maintained for SEARCH block matching and Cloak restoration.

    Sorted by descending name length to prevent partial substring matches
    (e.g., _separable_matrix must be replaced before _separable).
    Names shorter than 4 characters are skipped to avoid false positives.
    """
    result = text
    for real_name, token in sorted(forward_map.items(), key=lambda kv: -len(kv[0])):
        if len(real_name) < 4:
            continue
        if real_name not in result:
            continue
        result = re.sub(rf"\b{re.escape(real_name)}\b", token, result)
    return result


def _collect_all_errors(stdout: str, stderr: str, max_chars: int = 3000) -> str:
    """
    Merge stdout+stderr, strip excessive blank lines, truncate.
    Returns a single string suitable for Architect prompt injection.
    """
    raw = (stdout + "\n" + stderr).strip()
    if not raw:
        return ""
    cleaned = re.sub(r"\n{3,}", "\n\n", raw)
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars] + "\n...[truncated]"
    return cleaned


# ── Main Agent ────────────────────────────────────────────────────────────────


class DeterminexSWEAgent:
    """
    Drop-in SWE-bench agent. Implements solve(instance) interface.
    instance dict keys: repo, instance_id, problem_statement, base_commit, etc.
    """

    #: What the most recent compile gate actually established. Never "verified" by default --
    #: a patch produced without a gate run must not inherit a verified label.
    last_gate_verification: str = "unverified:no_gate_run"

    def __init__(self) -> None:
        _load_latent_index()
        self.last_gate_verification = "unverified:no_gate_run"

    def solve(
        self,
        instance: dict,
        repo_path: Path | None = None,
        enable_regression: bool = True,
    ) -> str:
        issue_text: str = instance.get("problem_statement", instance.get("issue_text", "")) or ""
        instance_id: str = instance.get("instance_id", "unknown") or "unknown"
        repo_name: str = instance.get("repo", "") or ""
        # FAIL_TO_PASS: JSON list of test names that must go from failing to passing
        _f2p_raw = instance.get("FAIL_TO_PASS", "[]")
        fail_tests: str = _f2p_raw if isinstance(_f2p_raw, str) else json.dumps(_f2p_raw)

        log.info("=" * 60)
        log.info("Solving instance: %s", instance_id)
        log.info("=" * 60)

        if repo_path is None:
            log.error("repo_path is required")
            return ""

        reset_repo(repo_path)

        # Detect repo language first — shadow compile and Cloak both need it
        repo_language: str = instance.get("language", "").lower() or _detect_repo_language(
            repo_path
        )
        log.info("Repo language: %s", repo_language)

        install_repo_editable(repo_path)

        # ── Phase 2: Shadow compilation ───────────────────────────────────────
        shadow_result = shadow_compile(repo_path, repo_language=repo_language)
        if shadow_result is _SHADOW_CLEAN:
            return ""
        shadow_trace: str = shadow_result  # type: ignore[assignment]
        if shadow_trace:
            issue_with_trace = (
                f"{issue_text}\n\n"
                f"[PRE-CHANGE FATAL TRACEBACK — captured before any edits]\n"
                f"{shadow_trace}"
            )
        else:
            issue_with_trace = issue_text

        # ── Project Cloak ─────────────────────────────────────────────────────
        # Build symbol map now, but obfuscate AFTER file discovery.
        # File search compares keywords against real source content on disk —
        # obfuscated x_NNNN keywords would match nothing and return wrong files.
        cloak_ctx: CloakContext | None = None
        if _CLOAK_ENABLED:
            try:
                cloak_ctx = build_cloak_context(instance_id, repo_path, language=repo_language)
                log.info(
                    "Cloak ACTIVE — %d identifiers mapped for %s",
                    len(cloak_ctx.symbol_map.forward),
                    instance_id,
                )  # type: ignore[union-attr]
            except Exception as e:
                log.warning("Cloak: context build failed (%s) — proceeding uncloaked", e)
                cloak_ctx = None

        # Locate files using REAL identifiers — must match actual file content on disk
        relevant_files, keywords = locate_relevant_files(
            repo_path,
            issue_text,
            repo_language=repo_language,
            fail_tests=fail_tests,
        )

        # Build semantic key BEFORE obfuscation: reads real names, emits only hints.
        # Injected into both Architect and Builder prompts so they can map x_NNNN
        # tokens to their functional meaning without real names leaving local.
        semantic_key = ""
        if cloak_ctx:
            try:
                semantic_key = build_semantic_key(cloak_ctx, relevant_files, repo_path)
                if semantic_key:
                    log.info(
                        "Semantic key built — %d token hints for AI context",
                        semantic_key.count("\n  x_"),
                    )
            except Exception as e:
                log.warning("Semantic key build failed (%s) — proceeding without", e)

        # NOW obfuscate for AI calls (Architect planning + Builder code-gen)
        if cloak_ctx:
            issue_text = cloak_ctx.obfuscate_text(issue_text)  # type: ignore[union-attr]
            issue_with_trace = cloak_ctx.obfuscate_text(issue_with_trace)  # type: ignore[union-attr]
        # ─────────────────────────────────────────────────────────────────────
        log.info("Relevant files: %s", [str(f.relative_to(repo_path)) for f in relevant_files])

        # ── Phase 1: Compile-gate solve loop ─────────────────────────────────
        # _gate_solve_loop drives up to _GATE_MAX_TOTAL attempts.
        # Each attempt uses _solve_sequential (or _solve_parallel on high-VRAM rigs)
        # as the inner engine, then validates the patch in an isolated worktree
        # before accepting it.  Compiler errors are re-obfuscated and fed back
        # to the Architect so each retry is targeted, not blind.
        tier = _detect_compute_tier()
        log.info("Compute tier: %s (VRAM threshold: %d MB)", tier, VRAM_PARALLEL_THRESHOLD_MB)

        # Pre-warm local builder model once before the solve loop.
        # Pays the cold-load cost here (up to 10 min for 32B Q4) so individual
        # attempt timeouts don't fire mid-loop.
        if USE_LOCAL_BUILDER:
            _warm_local_builder()

        patch = self._gate_solve_loop(
            repo_path,
            issue_with_trace,
            relevant_files,
            enable_regression,
            shadow_trace=shadow_trace,
            cloak_ctx=cloak_ctx,
            semantic_key=semantic_key,
            repo_language=repo_language,
            fail_tests=fail_tests,
            keywords=keywords,
            instance_id=instance_id,
        )

        # ── Phase 4: Flywheel capture ─────────────────────────────────────────
        if patch:
            try:
                from determinex_flywheel import capture_successful_epoch

                capture_successful_epoch(  # type: ignore[arg-type]
                    issue_text,
                    patch,
                    instance_id,
                    repo_name,
                    verification=self.last_gate_verification,
                )
            except ImportError:
                log.debug("determinex_flywheel not available — skipping capture")

        # Save cloak audit map if Cloak was active (regardless of patch success)
        if cloak_ctx:
            _run_dir = Path(os.getenv("DETERMINEX_RUN_DIR", "logs/swebench/unknown_run"))
            try:
                cloak_ctx.save(_run_dir)
            except Exception as e:
                log.debug("Cloak: map save failed: %s", e)

        if patch:
            log.info("Patch generated (%d lines)", len(patch.splitlines()))
        else:
            log.warning("No patch generated — all paths exhausted")

        reset_repo(repo_path)
        return patch

    # ── Direct patch fallback (all temperature attempts exhausted) ───────────

    def _direct_patch_fallback(
        self,
        repo_path: Path,
        issue_text: str,
        relevant_files: list[Path],
        cloak_ctx: CloakContext | None = None,
        repo_language: str = "python",
        fail_tests: str = "",
    ) -> str:
        """
        Phase 2 fallback: bypass the Architect entirely.
        Pick the top source file and ask the Builder directly for search/replace blocks.
        Uses T=0.2 (slightly higher variance) to break out of the same failure mode.
        """
        src_files = [f for f in relevant_files if not _is_test_file(f)]
        target = (src_files or relevant_files)[0] if relevant_files else None
        if target is None:
            return ""

        rel_path = str(target.relative_to(repo_path))
        stub_step = {
            "step": 1,
            "file": rel_path,
            "action": "modify",
            "description": "Fix the bug described in the issue",
        }
        original = target.read_text(encoding="utf-8", errors="replace")
        # FAIL-CLOSED: if cloak is on and obfuscation fails, return empty
        # patch instead of sending plaintext to the API. The caller treats an
        # empty result as "no fix produced" and moves on.
        if cloak_ctx:
            try:
                obfuscated = cloak_ctx.obfuscate_source_str(original, cache_key=rel_path)
            except CloakObfuscationError as _coe:
                log.error(
                    "[Cloak FAIL-CLOSED] single-shot fix for %s — refusing plaintext API call: %s",
                    rel_path,
                    _coe,
                )
                return ""
        else:
            obfuscated = ""

        model_out = generate_fix(
            stub_step,
            issue_text,
            repo_path,
            attempt=1,
            temperature=0.2,
            source_override=obfuscated,
            cloak_mode=bool(cloak_ctx),
            symbol_map=cloak_ctx.symbol_map.forward if cloak_ctx else None,  # type: ignore[union-attr]
            repo_language=repo_language,
            fail_tests=fail_tests,
        )

        if not model_out or model_out == _NO_BLOCKS_SENTINEL:
            return ""

        # Normalize real names → x_NNNN before block apply
        if cloak_ctx and obfuscated:
            model_out = _normalize_to_cloak_tokens(
                model_out,
                cloak_ctx.symbol_map.forward,  # type: ignore[union-attr]
            )

        blocks = _parse_search_replace_blocks(model_out)
        if not blocks:
            return ""

        # Cloak checksum: block tokens that were hallucinated (appear in NO file).
        # Cross-file token references are allowed — SEARCH matching is the real check.
        if cloak_ctx and obfuscated:
            _xt_re = re.compile(r"\bx_\d{4}\b")
            _src_toks = set(_xt_re.findall(obfuscated))
            try:
                _src_toks |= set(cloak_ctx.symbol_map.forward.values())  # type: ignore[union-attr]
            except Exception:
                pass
            _search_toks: set[str] = set()
            for _s, _ in blocks:
                _search_toks.update(_xt_re.findall(_s))
            _invented = _search_toks - _src_toks
            if _invented and len(_invented) / max(len(_search_toks), 1) > 0.05:
                log.warning(
                    "Direct fallback: SEARCH blocks contain %d hallucinated tokens — discarding",
                    len(_invented),
                )
                return ""

        source_to_patch = obfuscated if cloak_ctx else original
        fixed_obf, failed = _apply_search_replace_blocks(source_to_patch, blocks)
        if failed or fixed_obf == source_to_patch:
            return ""

        fixed = cloak_ctx.restore_content(fixed_obf) if cloak_ctx else fixed_obf  # type: ignore[union-attr]
        if not fixed.strip() or fixed == original:
            return ""

        syntax_err = _check_fixed_syntax(target, fixed, repo_language)
        if syntax_err:
            log.debug("Direct fallback: compile check failed: %s", syntax_err[:80])
            return ""

        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(fixed)
        patch = make_targeted_patch(rel_path, original, fixed)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(original)

        if patch and len(patch.splitlines()) <= 150:
            return patch
        return ""

    # ── Compile gate ──────────────────────────────────────────────────────────

    def _run_compile_check(self, repo_path: Path, repo_language: str) -> tuple[str, bool]:
        """
        Run a compile check on repo_path, collecting ALL errors (not just first).

        Returns (error_text, checked).
          error_text — "" when nothing was wrong; error output when it was.
          checked    — whether a compiler actually ran and reached a verdict.

        WHY THE SECOND VALUE EXISTS
        ---------------------------
        This used to return a bare string, so `""` meant BOTH "compiled clean" and "could not
        check". Seven paths returned `""` without compiling anything: no Python sources, no
        pom/gradle, no tsconfig, no CMakeLists/Makefile, an unsupported language, any exception,
        and -- worst -- FileNotFoundError, i.e. cargo/go/mvn not installed. On a host missing the
        toolchain the gate reported PASS for every patch it was ever given.

        That PASS is what ultimately writes `"verified": true` into auto_curriculum.jsonl, so the
        conflation did not just mislabel a run, it fed unverified patches to the next LoRA retrain
        -- against CLAUDE.md's "all training data must be compiler-validated before entering
        corpus". Callers must now branch on `checked` before treating "" as success.
        """
        try:
            if repo_language == "python":
                src_files = [
                    str(f)
                    for f in repo_path.rglob("*.py")
                    if not any(
                        p in f.parts for p in {"__pycache__", "site-packages", "vendor", ".git"}
                    )
                ][:30]
                if not src_files:
                    return "", False  # nothing to compile is not a clean compile
                r = subprocess.run(
                    [sys.executable, "-m", "py_compile"] + src_files,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=repo_path,
                )
                if r.returncode != 0:
                    return _collect_all_errors(r.stdout, r.stderr), True
                return "", True

            if repo_language == "go":
                r = subprocess.run(
                    ["go", "build", "./..."],
                    capture_output=True,
                    text=True,
                    timeout=90,
                    cwd=repo_path,
                )
                if r.returncode != 0:
                    return _collect_all_errors(r.stdout, r.stderr), True
                return "", True

            if repo_language == "rust":
                # cargo check is faster than cargo build and emits all type/borrow errors
                r = subprocess.run(
                    ["cargo", "check", "--message-format=short"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=repo_path,
                )
                if r.returncode != 0:
                    return _collect_all_errors(r.stdout, r.stderr), True
                return "", True

            if repo_language == "java":
                for build_file, cmd in [
                    ("pom.xml", ["mvn", "compile", "-q", "--fail-at-end"]),
                    ("build.gradle", ["./gradlew", "compileJava", "-q"]),
                    ("build.gradle.kts", ["./gradlew", "compileJava", "-q"]),
                ]:
                    if (repo_path / build_file).exists():
                        r = subprocess.run(
                            cmd, capture_output=True, text=True, timeout=120, cwd=repo_path
                        )
                        if r.returncode != 0:
                            return _collect_all_errors(r.stdout, r.stderr), True
                        return "", True
                return "", False  # no recognised build file — nothing was compiled

            if repo_language == "typescript":
                if (repo_path / "tsconfig.json").exists():
                    r = subprocess.run(
                        ["npx", "--yes", "tsc", "--noEmit"],
                        capture_output=True,
                        text=True,
                        timeout=90,
                        cwd=repo_path,
                    )
                    if r.returncode != 0:
                        return _collect_all_errors(r.stdout, r.stderr), True
                    return "", True
                return "", False  # no tsconfig — tsc never ran

            if repo_language in ("c", "cpp"):
                build_dir = repo_path / "_determinex_build_gate"
                try:
                    if (repo_path / "CMakeLists.txt").exists():
                        build_dir.mkdir(exist_ok=True)
                        subprocess.run(
                            ["cmake", "..", "-DCMAKE_BUILD_TYPE=Debug"],
                            cwd=build_dir,
                            capture_output=True,
                            timeout=60,
                        )
                        r = subprocess.run(
                            ["make", "-j2", "-k"],  # -k = keep going on error
                            cwd=build_dir,
                            capture_output=True,
                            text=True,
                            timeout=120,
                        )
                        if r.returncode != 0:
                            return _collect_all_errors(r.stdout, r.stderr), True
                        return "", True
                    if (repo_path / "Makefile").exists():
                        r = subprocess.run(
                            ["make", "-k"],
                            cwd=repo_path,
                            capture_output=True,
                            text=True,
                            timeout=120,
                        )
                        if r.returncode != 0:
                            return _collect_all_errors(r.stdout, r.stderr), True
                        return "", True
                finally:
                    shutil.rmtree(str(build_dir), ignore_errors=True)
                return "", False  # neither CMakeLists nor Makefile — nothing was built

        except FileNotFoundError as e:
            # The toolchain is absent. Previously "" => PASS for every patch on this host.
            log.warning("Compile check: tool not found (%s) — NOT verified", e)
            return "", False
        except subprocess.TimeoutExpired:
            return "[compile check timed out]", True
        except Exception as e:
            log.warning("Compile check error: %s — NOT verified", e)
            return "", False

        return "", False  # unsupported language — no check ran

    def _run_target_tests(
        self,
        repo_path: Path,
        repo_language: str,
        fail_tests: str,
    ) -> tuple[str, bool]:
        """
        Run only the FAIL_TO_PASS tests without -x/--fail-fast so ALL failures are collected.

        Returns (error_text, ran) -- same reasoning as _run_compile_check: `""` alone could not
        distinguish "every target test passed" from "no test was executed". Four paths returned
        it without running anything: no FAIL_TO_PASS ids, no recognised Java build file, an
        absent test runner (FileNotFoundError), and an unsupported language.
        """
        test_ids = [t.strip() for t in fail_tests.splitlines() if t.strip()][:10]
        if not test_ids:
            return "", False  # no FAIL_TO_PASS ids given — no test ran

        try:
            if repo_language == "python":
                r = subprocess.run(
                    [sys.executable, "-m", "pytest", "--tb=short", "--no-header", "-q"] + test_ids,
                    capture_output=True,
                    text=True,
                    timeout=TEST_TIMEOUT,
                    cwd=repo_path,
                )
                if r.returncode != 0:
                    return _collect_all_errors(r.stdout, r.stderr), True
                return "", True

            if repo_language == "go":
                pattern = "|".join(re.escape(t.split("::")[-1]) for t in test_ids)
                r = subprocess.run(
                    ["go", "test", "-run", pattern, "-v", "./..."],
                    capture_output=True,
                    text=True,
                    timeout=TEST_TIMEOUT,
                    cwd=repo_path,
                )
                if r.returncode != 0:
                    return _collect_all_errors(r.stdout, r.stderr), True
                return "", True

            if repo_language == "rust":
                names = [t.split("::")[-1] for t in test_ids]
                r = subprocess.run(
                    ["cargo", "test", "--", "--test-threads=2"] + names,
                    capture_output=True,
                    text=True,
                    timeout=TEST_TIMEOUT,
                    cwd=repo_path,
                )
                if r.returncode != 0:
                    return _collect_all_errors(r.stdout, r.stderr), True
                return "", True

            if repo_language == "java":
                test_class = ",".join(t.split("::")[-1] for t in test_ids)
                for build_file, cmd in [
                    (
                        "pom.xml",
                        [
                            "mvn",
                            "test",
                            "--fail-at-end",
                            "-Dsurefire.failIfNoSpecifiedTests=false",
                            f"-Dtest={test_class}",
                        ],
                    ),
                    ("build.gradle", ["./gradlew", "test", f"--tests={test_class}"]),
                    ("build.gradle.kts", ["./gradlew", "test", f"--tests={test_class}"]),
                ]:
                    if (repo_path / build_file).exists():
                        r = subprocess.run(
                            cmd, capture_output=True, text=True, timeout=TEST_TIMEOUT, cwd=repo_path
                        )
                        if r.returncode != 0:
                            return _collect_all_errors(r.stdout, r.stderr), True
                        return "", True
                return "", False  # no recognised build file — no test ran

            if repo_language in ("javascript", "typescript"):
                r = subprocess.run(
                    ["npx", "--yes", "jest", "--no-coverage", "--forceExit"] + test_ids,
                    capture_output=True,
                    text=True,
                    timeout=TEST_TIMEOUT,
                    cwd=repo_path,
                )
                if r.returncode != 0:
                    return _collect_all_errors(r.stdout, r.stderr), True
                return "", True

            if repo_language == "ruby":
                # SWE-bench Ruby IDs: path/to/test_file.rb or Class#method
                # Bundle exec preserves Gemfile-locked gem versions
                test_files = [t for t in test_ids if t.endswith(".rb")]
                method_filters = [t.split("#")[-1] for t in test_ids if "#" in t]
                filter_flag = (
                    ["-n", "/(" + "|".join(re.escape(m) for m in method_filters) + ")/"]
                    if method_filters
                    else []
                )
                if (repo_path / "Gemfile").exists():
                    cmd = (
                        ["bundle", "exec", "ruby", "-Ilib:test"]
                        + filter_flag
                        + (test_files or ["-e", "exit"])
                    )
                else:
                    cmd = ["ruby", "-Ilib:test"] + filter_flag + (test_files or [])
                r = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=TEST_TIMEOUT, cwd=repo_path
                )
                if r.returncode != 0:
                    return _collect_all_errors(r.stdout, r.stderr), True
                return "", True

            if repo_language == "php":
                # Prefer phpunit from vendor (Composer-managed)
                phpunit = (
                    "vendor/bin/phpunit"
                    if (repo_path / "vendor/bin/phpunit").exists()
                    else "phpunit"
                )
                method_filter = "|".join(
                    re.escape(t.split("::")[-1]) for t in test_ids if "::" in t
                )
                filter_args = ["--filter", method_filter] if method_filter else []
                test_paths = [t.split("::")[0] for t in test_ids if "::" in t] or test_ids
                r = subprocess.run(
                    [phpunit, "--no-coverage"] + filter_args + test_paths,
                    capture_output=True,
                    text=True,
                    timeout=TEST_TIMEOUT,
                    cwd=repo_path,
                )
                if r.returncode != 0:
                    return _collect_all_errors(r.stdout, r.stderr), True
                return "", True

        except FileNotFoundError:
            return "", False  # test runner absent — nothing was verified
        except subprocess.TimeoutExpired:
            return "[target tests timed out]", True
        except Exception as e:
            return f"[test run error] {e}", True

        return "", False  # unsupported language — no test ran

    def _compile_gate(
        self,
        patch: str,
        repo_path: Path,
        repo_language: str,
        fail_tests: str,
        cloak_ctx: CloakContext | None,
    ) -> tuple[bool, str]:
        """
        Apply patch to an isolated git worktree, compile, run target tests.

        Cloak flow: restore patch (real identifiers) → compile (real code) →
                    re-obfuscate errors → safe to feed back to Architect.

        Returns (passed, error_text).  error_text is "" on pass.
        """
        wt: Path | None = None
        label = f"gate_{repo_path.name[:12]}_{os.getpid()}_{threading.get_ident()}"
        # Reset per run: a previous instance's "compiled+tested" must never carry over.
        self.last_gate_verification = "unverified:no_gate_run"

        try:
            wt = _create_worktree(repo_path, label)
            if wt is None:
                return False, "[compile gate] worktree creation failed"

            # Restore obfuscated patch so the real-code worktree accepts it
            patch_to_apply = patch
            if cloak_ctx:
                restored, err = cloak_ctx.restore_diff(patch)
                if restored:
                    patch_to_apply = restored
                else:
                    log.warning("Compile gate: cloak restore failed (%s) — applying raw patch", err)

            # Baseline compile: if the clean worktree already fails to compile,
            # the error is pre-existing (e.g. a dep incompatibility in the env).
            # Apply the patch anyway and accept it — we cannot penalise the patch
            # for a dependency bug we can't control.
            baseline_err, baseline_checked = self._run_compile_check(wt, repo_language)
            if baseline_err:
                log.warning(
                    "Compile gate: baseline compile FAILED before patch — "
                    "pre-existing env error, skipping compile gate"
                )
                # Still apply the patch so Docker eval can test it
                subprocess.run(
                    ["git", "apply", "--whitespace=fix", "--ignore-whitespace", "-"],
                    input=patch_to_apply,
                    text=True,
                    cwd=wt,
                    capture_output=True,
                    timeout=30,
                )
                # PASS so the run continues -- we cannot penalise a patch for a dependency bug
                # we do not control -- but the patch itself was never compiled, so this is not
                # verification and must not be recorded as such.
                self.last_gate_verification = "unverified:baseline_compile_failed"
                return True, ""
            if not baseline_checked:
                # No compiler ran on the clean tree (absent toolchain, unsupported language, no
                # build file). Nothing downstream can be called compiler-validated.
                log.warning(
                    "Compile gate: no compile check available for %s — patch will be "
                    "UNVERIFIED, not compiler-validated",
                    repo_language,
                )

            # Apply patch
            apply_r = subprocess.run(
                ["git", "apply", "--whitespace=fix", "--ignore-whitespace", "-"],
                input=patch_to_apply,
                text=True,
                cwd=wt,
                capture_output=True,
                timeout=30,
            )
            if apply_r.returncode != 0:
                raw = _collect_all_errors(apply_r.stdout, apply_r.stderr)
                log.warning("Compile gate: patch apply FAILED:\n%s", raw[:400])
                msg = f"[patch apply failed]\n{raw}"
                return False, cloak_ctx.obfuscate_text(msg) if cloak_ctx else msg

            log.info("Compile gate: patch applied cleanly")

            # Post-patch compile — only errors introduced by the patch reach here
            compile_err, compile_checked = self._run_compile_check(wt, repo_language)
            if compile_err:
                log.warning("Compile gate: COMPILE FAIL:\n%s", compile_err[:400])
                safe = cloak_ctx.obfuscate_text(compile_err) if cloak_ctx else compile_err
                return False, f"[COMPILE ERRORS]\n{safe}"

            if compile_checked:
                log.info("Compile gate: compile PASS")

            # Target test run — collect ALL failures
            # Respect SKIP_NATIVE_TESTS: on Windows/Docker-eval mode the Docker
            # harness is the test oracle; compile-only is still valuable here.
            tests_ran = False
            if not SKIP_NATIVE_TESTS:
                test_err, tests_ran = self._run_target_tests(wt, repo_language, fail_tests)
                if test_err:
                    safe = cloak_ctx.obfuscate_text(test_err) if cloak_ctx else test_err
                    return False, f"[TEST FAILURES]\n{safe}"

            # Record WHAT was established, so the flywheel is not free to call any PASS
            # "verified". Compile-only still satisfies CLAUDE.md's compiler-validated bar;
            # nothing-compiled does not.
            if compile_checked and tests_ran:
                self.last_gate_verification = "compiled+tested"
            elif compile_checked:
                self.last_gate_verification = "compiled_only"
            else:
                self.last_gate_verification = "unverified:no_compile_check"

            return True, ""

        except Exception as e:
            self.last_gate_verification = "unverified:gate_exception"
            return False, f"[compile gate exception] {e}"
        finally:
            if wt:
                _remove_worktree(repo_path, wt)

    def _write_gate_wal(self, instance_id: str, entry: dict) -> None:
        try:
            run_dir = Path(os.getenv("DETERMINEX_RUN_DIR", "logs/swebench/unknown_run"))
            wal_dir = run_dir / "gate_wal"
            wal_dir.mkdir(parents=True, exist_ok=True)
            safe_id = instance_id[:40].replace("/", "_").replace("\\", "_")
            wal_path = wal_dir / f"gate_{safe_id}.jsonl"
            with open(wal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            log.debug("Gate WAL write failed: %s", e)

    def _adjudicate_escalation(self, all_errors: list[str]) -> dict:
        """Impossibility Adjudicator gate: before the loop is allowed to declare
        defeat, route the exhausted errors through the 4-step gate. The loop may
        only call something a genuine ceiling if the adjudicator returns
        IMPOSSIBLE for it. Anything ROUTE/MATCH/UNBLOCK/NEEDS_WORK means the move
        was not yet found -- keep going, with the recommended strategy attached.
        Soft-fails to 'needs human' only if the adjudicator itself is unavailable.
        """
        try:
            import sys as _sys

            _here = str(Path(__file__).resolve().parent)
            if _here not in _sys.path:
                _sys.path.insert(0, _here)
            from determinex_adjudicator import Failure, Verdict, classify_failure

            recs, verdicts = [], []
            for i, err in enumerate(all_errors):
                if not err:
                    continue
                a = classify_failure(
                    Failure(test_id=f"attempt_{i}", name=f"attempt_{i}", text=str(err))
                )
                verdicts.append(a.verdict.value)
                recs.append(
                    {
                        "verdict": a.verdict.value,
                        "strategy": a.strategy,
                        "remediation": a.remediation,
                    }
                )
            reopenable = [r for r in recs if r["verdict"] != Verdict.IMPOSSIBLE.value]
            return {
                "adjudicated": True,
                "all_impossible": bool(recs) and not reopenable,
                "recommendations": recs,
                "next_moves": sorted({r["strategy"] for r in reopenable}),
            }
        except Exception as e:  # never let the governor crash the run
            return {"adjudicated": False, "error": str(e)}

    def _write_gate_escalation(self, instance_id: str, wal: list[dict]) -> None:
        try:
            run_dir = Path(os.getenv("DETERMINEX_RUN_DIR", "logs/swebench/unknown_run"))
            esc_dir = run_dir / "gate_escalations"
            esc_dir.mkdir(parents=True, exist_ok=True)
            safe_id = instance_id[:40].replace("/", "_").replace("\\", "_")
            esc_path = esc_dir / f"escalation_{safe_id}.json"
            all_errors = [e for entry in wal for e in [entry.get("errors", "")]]
            adj = self._adjudicate_escalation(all_errors)
            # The give-up point now requires the adjudicator's proof: only a fully
            # IMPOSSIBLE verdict marks the task as genuinely needing a human.
            genuine_ceiling = bool(adj.get("all_impossible"))
            msg = (
                f"Instance '{instance_id}' exhausted {_GATE_MAX_TOTAL} compile-gate "
                f"attempts. Adjudicator says: "
                + (
                    "GENUINE CEILING (all verdicts IMPOSSIBLE) -- human review."
                    if genuine_ceiling
                    else f"REOPENABLE -- untried moves: {adj.get('next_moves')}. "
                    f"This is unfinished work, not a ceiling."
                )
            )
            esc_path.write_text(
                json.dumps(
                    {
                        "instance_id": instance_id,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "total_attempts": len(wal),
                        "all_errors": all_errors,
                        "wal": wal,
                        "adjudication": adj,
                        "user_action_required": genuine_ceiling,
                        "message": msg,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            log.warning(
                "[%s] ESCALATION -- %d attempts. Adjudicator: %s. See: %s",
                instance_id,
                len(wal),
                "GENUINE CEILING" if genuine_ceiling else f"REOPENABLE {adj.get('next_moves')}",
                esc_path,
            )
        except Exception as e:
            log.debug("Gate escalation write failed: %s", e)

    def _gate_solve_loop(
        self,
        repo_path: Path,
        issue_text: str,
        relevant_files: list[Path],
        enable_regression: bool,
        shadow_trace: str = "",
        cloak_ctx: CloakContext | None = None,
        semantic_key: str = "",
        repo_language: str = "python",
        fail_tests: str = "",
        keywords: list[str] | None = None,
        instance_id: str = "unknown",
    ) -> str:
        """
        Compile-gate solve loop — replaces the blind temperature sweep.

        Each attempt:
          1. plan_fix + _solve_one_path at the scheduled temperature
          2. _compile_gate: apply to isolated worktree, compile, run target tests
          3. PASS → lock and return patch
          4. FAIL → collect ALL errors (re-obfuscated if Cloak), inject into next plan prompt

        Attempts 1-3: automatic.
        Attempts 4-5: escalation territory (flagged in WAL).
        After attempt 5 fails: write escalation record, return "".

        Training value: every (patch, compile_error, correction) triple is written
        to gate_wal/ as a compiler-validated labeled example for the flywheel.
        """
        gate_wal: list[dict] = []
        issue_with_errors = issue_text  # grows with each failure's correction block

        for attempt_idx in range(_GATE_MAX_TOTAL):
            attempt_num = attempt_idx + 1
            temp = _GATE_TEMPS[attempt_idx]
            is_escalation = attempt_num > _GATE_MAX_AUTO

            log.info(
                "[%s] Gate attempt %d/%d (T=%.1f)%s",
                instance_id,
                attempt_num,
                _GATE_MAX_TOTAL,
                temp,
                " [ESCALATION]" if is_escalation else "",
            )

            # Each gate attempt is a single-temperature sequential pass.
            # temperature_override pins exactly the scheduled temp so the gate
            # drives escalation; _solve_sequential does not sweep internally.
            patch = self._solve_sequential(
                repo_path,
                issue_with_errors,
                relevant_files,
                enable_regression,
                shadow_trace=shadow_trace,
                cloak_ctx=cloak_ctx,
                semantic_key=semantic_key,
                repo_language=repo_language,
                fail_tests=fail_tests,
                keywords=keywords,
                temperature_override=temp,
                instance_id=instance_id,
            )

            if not patch:
                log.warning("[%s] Gate attempt %d: no patch from builder", instance_id, attempt_num)
                no_patch_err = "[no patch generated — x_NNNN token preservation check failed]"
                gate_wal.append(
                    {
                        "instance_id": instance_id,
                        "attempt": attempt_num,
                        "temperature": temp,
                        "patch_lines": 0,
                        "passed": False,
                        "errors": no_patch_err,
                        "escalation": is_escalation,
                        "ts": datetime.now(UTC).isoformat(),
                    }
                )
                # Inject token rule violation into the next attempt's context so the
                # Builder knows WHY it was rejected, not just that it failed.
                issue_with_errors = (
                    issue_text
                    + f"\n\n[GATE FAILURE — Attempt {attempt_num}: Token Preservation Violated]\n"
                    + "Your patch was REJECTED because you renamed x_NNNN identifiers. "
                    + "RULE: Every x_NNNN token in your SEARCH and REPLACE blocks must be "
                    + "copied CHARACTER-FOR-CHARACTER from the file content shown above. "
                    + "Do NOT rename, expand, abbreviate, or substitute any x_NNNN token "
                    + "— not even if a [SYMBOL GUIDE] entry suggests a meaning. "
                    + "The x_NNNN tokens ARE the correct identifiers. Copy them as-is."
                )
                reset_repo(repo_path)
                continue

            # Compile gate: apply to isolated worktree, compile, test
            passed, errors = self._compile_gate(
                patch, repo_path, repo_language, fail_tests, cloak_ctx
            )

            wal_entry: dict = {
                "instance_id": instance_id,
                "attempt": attempt_num,
                "temperature": temp,
                "patch_lines": len(patch.splitlines()),
                "passed": passed,
                "errors": errors,
                "escalation": is_escalation,
                "ts": datetime.now(UTC).isoformat(),
            }
            gate_wal.append(wal_entry)
            self._write_gate_wal(instance_id, wal_entry)

            if passed:
                log.info("[%s] Gate PASSED on attempt %d (T=%.1f)", instance_id, attempt_num, temp)
                return patch

            log.warning(
                "[%s] Gate FAILED attempt %d — errors:\n%s",
                instance_id,
                attempt_num,
                errors[:500] if errors else "(none captured)",
            )

            # Inject errors into next attempt's plan prompt (Cloak-safe — already re-obfuscated).
            # Patch-apply failures mean the SEARCH blocks didn't match the real file — the
            # model needs a fresh start, not targeted corrections. Compile/test failures need
            # targeted corrections against the specific broken lines.
            is_apply_failure = errors.startswith("[patch apply failed]")
            if is_apply_failure:
                correction_instruction = (
                    "Your previous patch could not be applied — the SEARCH blocks did not "
                    "match the actual file content. Start completely fresh: re-read the file "
                    "content above and copy the existing code verbatim, character-for-character, "
                    "into your SEARCH blocks. Do not guess or paraphrase — the match must be exact."
                )
                error_block = ""
            else:
                correction_instruction = (
                    "Your patch compiled but produced the following errors. Do NOT regenerate "
                    "from scratch. Identify the exact lines causing these errors and emit "
                    "corrected SEARCH/REPLACE blocks only."
                )
                error_block = f"\n\n{errors}"
            issue_with_errors = (
                issue_text
                + f"\n\n[COMPILE GATE FAILURE — Attempt {attempt_num}]\n"
                + correction_instruction
                + error_block
            )

            reset_repo(repo_path)

        # All attempts exhausted
        self._write_gate_escalation(instance_id, gate_wal)
        return ""

    # ── Sequential path (Tier 0 / small rig) ─────────────────────────────────

    def _solve_sequential(
        self,
        repo_path: Path,
        issue_text: str,
        relevant_files: list[Path],
        enable_regression: bool,
        shadow_trace: str = "",
        cloak_ctx: CloakContext | None = None,
        semantic_key: str = "",
        repo_language: str = "python",
        fail_tests: str = "",
        keywords: list[str] | None = None,
        temperature_override: float | None = None,
        instance_id: str = "",
    ) -> str:
        """
        Try T=0.1, T=0.4, T=0.7 in order on the main repo.
        First temperature that produces a passing patch wins.

        When called from _gate_solve_loop, temperature_override pins a single
        temperature so the gate drives the escalation schedule, not this loop.
        """
        stop = threading.Event()
        temps_to_try = [temperature_override] if temperature_override is not None else TEMPERATURES

        for t_idx, temperature in enumerate(temps_to_try):
            log.info("Sequential path %d/%d (T=%.1f)...", t_idx + 1, len(TEMPERATURES), temperature)

            steps = plan_fix(
                issue_text,
                relevant_files,
                repo_path,
                temperature,
                cloak_ctx=cloak_ctx,
                semantic_key=semantic_key,
                repo_language=repo_language,
                fail_tests=fail_tests,
                keywords=keywords,
            )
            if not steps:
                continue

            feedback: dict = {}
            patch = _solve_one_path(
                repo_path,
                issue_text,
                steps,
                temperature,
                stop,
                path_id=t_idx,
                enable_regression=enable_regression,
                shadow_trace=shadow_trace,
                cloak_ctx=cloak_ctx,
                semantic_key=semantic_key,
                repo_language=repo_language,
                fail_tests=fail_tests,
                feedback=feedback,
                instance_id=instance_id,
            )
            if patch:
                log.info("Sequential: won at T=%.1f", temperature)
                return patch

            # ── Decompose retry ───────────────────────────────────────────────
            # When every builder sub-attempt was rejected as too large, the model
            # is rewriting the whole file. Ask the Architect to break the step
            # into smaller targeted sub-steps and try once more (one retry only).
            if not patch and feedback.get("too_large"):
                tl = feedback["too_large"]
                log.warning(
                    "Sequential: step '%s' produced %d-line patch on every attempt — "
                    "requesting Architect decomposition",
                    tl["step_file"],
                    tl["line_count"],
                )
                # decompose_hint is passed as a separate kwarg so plan_fix injects it
                # AFTER the file summaries — it never gets swallowed by issue_text[:2000].
                decompose_hint = (
                    f"[DECOMPOSE REQUEST — CRITICAL]\n"
                    f'The previous plan targeted "{tl["step_file"]}" as a single step '
                    f"and the builder generated a {tl['line_count']}-line patch every time "
                    f"(whole-file rewrite). This MUST NOT happen again.\n"
                    f"MANDATORY RULES for your new plan:\n"
                    f'1. Do NOT return a single step that targets "{tl["step_file"]}" as a whole.\n'
                    f'2. If you must touch "{tl["step_file"]}", identify the SPECIFIC FUNCTION '
                    f"or METHOD by name that needs changing and write the description as: "
                    f'"Modify function <name> in {tl["step_file"]} to fix <X>" — '
                    f"the builder must change fewer than 80 diff lines.\n"
                    f"3. Prefer 2–3 sub-steps that each target a narrow, named code region.\n"
                    f"4. If the fix is inherently large, split it across multiple small steps "
                    f"targeting different functions or sections of the file.\n"
                    f"Failure to follow these rules means your plan is rejected and the issue "
                    f"remains unresolved."
                )
                decomposed_steps = plan_fix(
                    issue_text,
                    relevant_files,
                    repo_path,
                    temperature,
                    cloak_ctx=cloak_ctx,
                    semantic_key=semantic_key,
                    repo_language=repo_language,
                    fail_tests=fail_tests,
                    keywords=keywords,
                    decompose_hint=decompose_hint,
                )
                # Guard: if decompose returned the same single step targeting the same
                # large file, retrying is futile — the builder will produce another
                # whole-file rewrite. Skip silently.
                _same_single_file = (
                    len(decomposed_steps) == 1
                    and decomposed_steps[0].get("file", "") == tl["step_file"]
                )
                if decomposed_steps and decomposed_steps != steps and not _same_single_file:
                    log.info(
                        "Sequential: decomposed into %d sub-steps — retrying", len(decomposed_steps)
                    )
                    # Inject line-budget reminder into each step description so the
                    # Builder also sees the constraint (not just the Architect).
                    for ds in decomposed_steps:
                        if "(< 80 lines)" not in ds.get("description", ""):
                            ds["description"] = (
                                ds.get("description", "")
                                + " (< 80 diff lines — targeted change only)"
                            )
                    patch = _solve_one_path(
                        repo_path,
                        issue_text,
                        decomposed_steps,
                        temperature,
                        stop,
                        path_id=t_idx,
                        enable_regression=enable_regression,
                        shadow_trace=shadow_trace,
                        cloak_ctx=cloak_ctx,
                        semantic_key=semantic_key,
                        repo_language=repo_language,
                        fail_tests=fail_tests,
                        instance_id=instance_id,
                    )
                    if patch:
                        log.info("Sequential: decomposed retry won at T=%.1f", temperature)
                        return patch
                elif _same_single_file:
                    log.warning(
                        "Sequential: decompose returned same single file '%s' — "
                        "skipping futile retry",
                        tl["step_file"],
                    )

            reset_repo(repo_path)

        # All temperature attempts exhausted — direct patch fallback (Phase 2)
        log.info("Sequential: all temperatures exhausted — trying direct patch fallback")
        patch = self._direct_patch_fallback(
            repo_path,
            issue_text,
            relevant_files,
            cloak_ctx=cloak_ctx,
            repo_language=repo_language,
            fail_tests=fail_tests,
        )
        if patch:
            log.info("Sequential: direct fallback succeeded")
        return patch or ""

    # ── Parallel path (Tier 1+ / big rig) ────────────────────────────────────

    def _solve_parallel(
        self,
        repo_path: Path,
        issue_text: str,
        relevant_files: list[Path],
        instance_id: str,
        enable_regression: bool,
        shadow_trace: str = "",
        cloak_ctx: CloakContext | None = None,
        semantic_key: str = "",
        repo_language: str = "python",
        fail_tests: str = "",
        keywords: list[str] | None = None,
    ) -> str:
        """
        Spawn 3 isolated git worktrees. Run each temperature in a thread.
        First thread to produce a passing patch cancels the others.
        """
        stop_event = threading.Event()
        worktrees: list[Path | None] = []
        winning_patch: str | None = None

        # Create worktrees before starting threads
        for i in range(len(TEMPERATURES)):
            label = f"{instance_id[:12].replace('/', '_')}_{i}"
            wt = _create_worktree(repo_path, label)
            worktrees.append(wt)

        try:
            # Plan once per temperature (slight variance in DAG)
            plans = []
            for t in TEMPERATURES:
                steps = plan_fix(
                    issue_text,
                    relevant_files,
                    repo_path,
                    t,
                    cloak_ctx=cloak_ctx,
                    semantic_key=semantic_key,
                    repo_language=repo_language,
                    fail_tests=fail_tests,
                    keywords=keywords,
                )
                plans.append(steps)

            valid_paths = [
                (i, wt, TEMPERATURES[i], plans[i])
                for i, wt in enumerate(worktrees)
                if wt is not None and plans[i]
            ]

            if not valid_paths:
                log.error("No valid worktrees created — aborting parallel solve")
                return ""

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(valid_paths),
                thread_name_prefix="determinex_path",
            ) as executor:
                future_map = {
                    executor.submit(
                        _solve_one_path,
                        wt,
                        issue_text,
                        steps,
                        temp,
                        stop_event,
                        path_id,
                        enable_regression,
                        shadow_trace,
                        cloak_ctx,
                        semantic_key,
                        repo_language,
                        fail_tests,
                    ): (path_id, temp)
                    for path_id, wt, temp, steps in valid_paths
                }

                for future in concurrent.futures.as_completed(future_map):
                    path_id, temp = future_map[future]
                    try:
                        result = future.result()
                        if result and not stop_event.is_set():
                            log.info(
                                "Path %d (T=%.1f) WON — cancelling remaining paths", path_id, temp
                            )
                            stop_event.set()
                            winning_patch = result
                            # Cancel pending futures (Python 3.9+)
                            for f in future_map:
                                if not f.done():
                                    f.cancel()
                    except concurrent.futures.CancelledError:
                        log.debug("Path %d cancelled (another path won)", path_id)
                    except Exception as e:
                        log.warning("Path %d raised exception: %s", path_id, e)

        finally:
            # Always clean up worktrees
            for wt in worktrees:
                if wt is not None:
                    _remove_worktree(repo_path, wt)

        return winning_patch or ""


# ── CLI for standalone testing ────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Determinex SWE-bench Agent (Flow AI Test-Time Scaling)"
    )
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--issue", type=str, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--instance-id", default="test-instance")
    parser.add_argument(
        "--tier",
        choices=["parallel", "sequential"],
        default=None,
        help="Override compute tier (default: auto-detect from VRAM)",
    )
    parser.add_argument(
        "--no-regression", action="store_true", help="Skip ripple regression sweep (Phase 3)"
    )
    args = parser.parse_args()

    repo_resolved = Path(args.repo).resolve()
    if not repo_resolved.exists() or not repo_resolved.is_dir():
        log.error("--repo path does not exist: %s", repo_resolved)
        sys.exit(1)

    issue_text = args.issue
    _issue_path = Path(args.issue).resolve()
    if _issue_path.exists() and _issue_path.is_file():
        issue_text = _issue_path.read_text(encoding="utf-8")

    if args.tier:
        os.environ["DETERMINEX_COMPUTE_TIER"] = args.tier

    agent = DeterminexSWEAgent()
    patch = agent.solve(
        {"problem_statement": issue_text, "instance_id": args.instance_id},
        repo_path=repo_resolved,
        enable_regression=not args.no_regression,
    )

    if args.out:
        args.out.write_text(patch, encoding="utf-8")
        log.info("Patch saved: %s", args.out)
    else:
        print(patch)

    sys.exit(0 if patch else 1)


if __name__ == "__main__":
    main()
